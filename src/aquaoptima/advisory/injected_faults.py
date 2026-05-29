"""Sprint 29 injected-fault harness.

Generate synthetic faults on otherwise-normal 2025 holdout-of-training rows from a
FROZEN seed, with ground-truth per-row labels and per-episode onset indices so the
gate can measure both detection AUROC and detection LEAD TIME.

Fault families (all parameters fixed; not tuned against the detector):

* ``sensor_drift`` -- a slow linear ramp added to one axis over a long window;
  models a creeping sensor or pump-degradation drift.
* ``stuck_flatline`` -- the chosen axis is held at a constant (its pre-onset mean)
  for the episode window; models a frozen sensor or stuck-output failure.
* ``spike`` -- a multi-sigma additive spike on one axis at a single timestep
  (followed by a short tail); models a transient instrumentation glitch.
* ``envelope_violation`` -- a multivariate physical-relationship break: power is
  pushed away from the (flow, pump-speed) regression expectation by adding a
  multi-sigma offset to ``edge_power`` while flow and speed remain coherent.

All onsets / lengths / axis selections are sampled from a single seeded
``numpy.random.default_rng`` so the harness is bit-identical across runs.

Hard boundary
-------------
Operates on a DataFrame caller already proved is 2025 / non-March-2026. The
harness does NOT call the leakage guard itself (the caller is responsible for
that on the source data), because injection deliberately mangles values that
would defeat a key-based guard run on the output.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np
import pandas as pd


# Default knobs -- FROZEN. Edit only with a documented sprint deliverable change.
DEFAULT_N_EPISODES_PER_KIND = 4
DEFAULT_DRIFT_WINDOW = 120        # rows
DEFAULT_DRIFT_END_SIGMAS = 4.0    # ramp end-magnitude in axis-sigmas
DEFAULT_STUCK_WINDOW = 80         # rows
DEFAULT_SPIKE_TAIL = 5            # rows after the spike step
DEFAULT_SPIKE_SIGMAS = 6.0        # spike magnitude in axis-sigmas
DEFAULT_ENVELOPE_WINDOW = 60      # rows
DEFAULT_ENVELOPE_SIGMAS = 4.0     # power offset in axis-sigmas
DEFAULT_SEED = 29


# Fault family identifiers (string-stable; used in onset records and reports).
FAULT_KINDS: tuple[str, ...] = (
    "sensor_drift",
    "stuck_flatline",
    "spike",
    "envelope_violation",
)


# Per-axis injection preferences. Drift / stuck / spike pick one axis at random
# from this list; envelope_violation always targets edge_power so the physical
# relationship breaks the way the Sprint-28 residual model expects.
INJECTABLE_AXES_DEFAULT: tuple[str, ...] = (
    "edge_flow",
    "edge_power",
    "edge_pump_speed",
    "node_pressure",
)


@dataclass(frozen=True)
class FaultEpisode:
    """One injected-fault episode applied to a contiguous row window."""

    kind: str
    axis: str
    onset_index: int           # 0-based row index of the first faulted row
    end_index: int             # 0-based row index AFTER the last faulted row
    magnitude_sigmas: float    # injection magnitude in standardised units
    parameters: Mapping[str, float] = field(default_factory=dict)

    @property
    def length(self) -> int:
        return int(self.end_index - self.onset_index)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "axis": self.axis,
            "onset_index": int(self.onset_index),
            "end_index": int(self.end_index),
            "length": int(self.length),
            "magnitude_sigmas": float(self.magnitude_sigmas),
            "parameters": {k: float(v) for k, v in dict(self.parameters).items()},
        }


@dataclass(frozen=True)
class InjectedFaultResult:
    """Output of :func:`inject_faults`."""

    frames: pd.DataFrame
    labels: np.ndarray         # per-row 0/1 anomaly label
    episodes: tuple[FaultEpisode, ...]
    seed: int
    knobs: Mapping[str, float] = field(default_factory=dict)

    def onsets_by_kind(self) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {k: [] for k in FAULT_KINDS}
        for ep in self.episodes:
            out.setdefault(ep.kind, []).append(int(ep.onset_index))
        return out

    def to_summary_dict(self) -> dict[str, object]:
        return {
            "seed": int(self.seed),
            "n_rows": int(len(self.frames)),
            "n_faulted_rows": int(self.labels.sum()),
            "fault_rate": float(self.labels.mean()) if self.labels.size else 0.0,
            "episodes": [ep.to_dict() for ep in self.episodes],
            "onsets_by_kind": self.onsets_by_kind(),
            "knobs": dict(self.knobs),
        }


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _per_axis_sigma(frames: pd.DataFrame, axes: Sequence[str]) -> dict[str, float]:
    """Sample stddev of each axis on the input frames (clamped >0).

    Used as the unit of fault magnitude so injections are comparable across axes
    regardless of physical scale.
    """
    out: dict[str, float] = {}
    for a in axes:
        x = frames[a].to_numpy(dtype=float)
        x = x[np.isfinite(x)]
        if x.size <= 1:
            out[a] = 1.0
            continue
        s = float(np.std(x, ddof=1))
        out[a] = s if s > 0 else 1.0
    return out


def _choose_windows(
    rng: np.random.Generator,
    n_rows: int,
    n_windows: int,
    window_len: int,
    *,
    min_gap: int = 5,
    forbidden: Sequence[tuple[int, int]] = (),
) -> list[tuple[int, int]]:
    """Pick non-overlapping ``(start, end)`` windows of length ``window_len``.

    ``forbidden`` is a list of prior ``(start, end)`` windows the picks must avoid;
    we keep at least ``min_gap`` rows between any two windows so labels do not
    contaminate one another.
    """
    if window_len <= 0 or n_windows <= 0 or n_rows <= 0:
        return []
    if window_len * n_windows + max(0, min_gap * (n_windows - 1)) > n_rows:
        raise ValueError(
            f"not enough rows ({n_rows}) for {n_windows} non-overlapping "
            f"window(s) of length {window_len} with gap {min_gap}"
        )
    chosen: list[tuple[int, int]] = list(forbidden)
    out: list[tuple[int, int]] = []
    attempts = 0
    max_attempts = 200 * max(1, n_windows)
    while len(out) < n_windows and attempts < max_attempts:
        attempts += 1
        start = int(rng.integers(low=0, high=max(1, n_rows - window_len + 1)))
        end = start + window_len
        if any(
            not (end + min_gap <= s or start >= e + min_gap) for s, e in chosen
        ):
            continue
        out.append((start, end))
        chosen.append((start, end))
    if len(out) < n_windows:
        raise RuntimeError(
            f"failed to find {n_windows} non-overlapping windows after "
            f"{attempts} attempts; try a smaller window or fewer episodes"
        )
    out.sort()
    return out


# --------------------------------------------------------------------------- #
# fault families
# --------------------------------------------------------------------------- #
def _apply_sensor_drift(
    arr: np.ndarray, start: int, end: int, sigma: float, magnitude_sigmas: float
) -> None:
    """Add a linear ramp from 0 to ``magnitude_sigmas * sigma`` over the window."""
    length = end - start
    if length <= 0:
        return
    ramp = np.linspace(0.0, float(magnitude_sigmas) * float(sigma), length)
    arr[start:end] = arr[start:end] + ramp


def _apply_stuck(arr: np.ndarray, start: int, end: int) -> None:
    """Replace the window with the pre-onset axis mean (constant flatline)."""
    if end <= start:
        return
    pre_window = arr[: start]
    pre_window = pre_window[np.isfinite(pre_window)]
    fill = float(pre_window.mean()) if pre_window.size else float(arr[start])
    arr[start:end] = fill


def _apply_spike(
    arr: np.ndarray, start: int, sigma: float, magnitude_sigmas: float, tail: int
) -> int:
    """Add a single multi-sigma spike at ``start`` with a short decaying tail."""
    if start >= arr.size:
        return start
    arr[start] = arr[start] + float(magnitude_sigmas) * float(sigma)
    # Short decaying tail so the episode label has more than one row.
    tail = max(0, int(tail))
    for i in range(1, tail + 1):
        if start + i >= arr.size:
            break
        decay = 0.5 ** i
        arr[start + i] = arr[start + i] + decay * float(magnitude_sigmas) * float(sigma)
    return min(arr.size, start + tail + 1)


def _apply_envelope_violation(
    power_arr: np.ndarray,
    start: int,
    end: int,
    sigma_power: float,
    magnitude_sigmas: float,
    sign: int,
) -> None:
    """Push ``edge_power`` away from the (flow, speed) expectation by a fixed offset.

    flow and pump_speed are deliberately left unchanged, so the joint Mahalanobis +
    physical residual baselines have a chance to surface the multivariate break.
    """
    if end <= start:
        return
    offset = float(sign) * float(magnitude_sigmas) * float(sigma_power)
    power_arr[start:end] = power_arr[start:end] + offset


# --------------------------------------------------------------------------- #
# main entry point
# --------------------------------------------------------------------------- #
def inject_faults(
    normal_frames: pd.DataFrame,
    *,
    seed: int = DEFAULT_SEED,
    n_episodes_per_kind: int = DEFAULT_N_EPISODES_PER_KIND,
    drift_window: int = DEFAULT_DRIFT_WINDOW,
    drift_magnitude_sigmas: float = DEFAULT_DRIFT_END_SIGMAS,
    stuck_window: int = DEFAULT_STUCK_WINDOW,
    spike_tail: int = DEFAULT_SPIKE_TAIL,
    spike_magnitude_sigmas: float = DEFAULT_SPIKE_SIGMAS,
    envelope_window: int = DEFAULT_ENVELOPE_WINDOW,
    envelope_magnitude_sigmas: float = DEFAULT_ENVELOPE_SIGMAS,
    injectable_axes: Sequence[str] = INJECTABLE_AXES_DEFAULT,
    min_gap: int = 5,
) -> InjectedFaultResult:
    """Inject the four fault families onto a copy of ``normal_frames``.

    Returns the faulted frame, per-row 0/1 labels, and per-episode metadata
    (including ``onset_index``). The harness is deterministic: identical ``seed``
    + identical ``normal_frames`` => identical output.

    Parameters are FROZEN by default. The Sprint-29 gate requires the empirical
    rule to be evaluated on the canonical knobs; callers should NOT tune these
    against the detector. Tests use smaller windows / fewer episodes to fit
    fixture-sized inputs.
    """
    if normal_frames.empty:
        raise ValueError("normal_frames is empty; nothing to inject into")
    rng = np.random.default_rng(int(seed))
    df = normal_frames.copy().reset_index(drop=True)
    n_rows = int(len(df))
    available_axes = [a for a in injectable_axes if a in df.columns]
    if len(available_axes) < 1:
        raise ValueError(
            f"no injectable axes present; expected any of {list(injectable_axes)}"
        )

    sigmas = _per_axis_sigma(df, available_axes)
    labels = np.zeros(n_rows, dtype=np.int8)
    episodes: list[FaultEpisode] = []
    used_windows: list[tuple[int, int]] = []

    # 1) sensor drift
    drift_windows = _choose_windows(
        rng, n_rows, n_episodes_per_kind, drift_window, min_gap=min_gap,
        forbidden=used_windows,
    )
    for start, end in drift_windows:
        axis = str(rng.choice(available_axes))
        s = sigmas[axis]
        arr = np.array(df[axis].to_numpy(dtype=float), copy=True)
        _apply_sensor_drift(arr, start, end, s, drift_magnitude_sigmas)
        df[axis] = arr
        labels[start:end] = 1
        used_windows.append((start, end))
        episodes.append(
            FaultEpisode(
                kind="sensor_drift",
                axis=axis,
                onset_index=int(start),
                end_index=int(end),
                magnitude_sigmas=float(drift_magnitude_sigmas),
                parameters={"sigma": float(s), "window": float(end - start)},
            )
        )

    # 2) stuck / flatline
    stuck_windows = _choose_windows(
        rng, n_rows, n_episodes_per_kind, stuck_window, min_gap=min_gap,
        forbidden=used_windows,
    )
    for start, end in stuck_windows:
        axis = str(rng.choice(available_axes))
        arr = np.array(df[axis].to_numpy(dtype=float), copy=True)
        _apply_stuck(arr, start, end)
        df[axis] = arr
        labels[start:end] = 1
        used_windows.append((start, end))
        episodes.append(
            FaultEpisode(
                kind="stuck_flatline",
                axis=axis,
                onset_index=int(start),
                end_index=int(end),
                magnitude_sigmas=0.0,
                parameters={"window": float(end - start)},
            )
        )

    # 3) spike (single step with a short decaying tail)
    spike_len = 1 + max(0, int(spike_tail))
    spike_windows = _choose_windows(
        rng, n_rows, n_episodes_per_kind, spike_len, min_gap=min_gap,
        forbidden=used_windows,
    )
    for start, _end in spike_windows:
        axis = str(rng.choice(available_axes))
        s = sigmas[axis]
        arr = np.array(df[axis].to_numpy(dtype=float), copy=True)
        new_end = _apply_spike(arr, start, s, spike_magnitude_sigmas, spike_tail)
        df[axis] = arr
        labels[start:new_end] = 1
        used_windows.append((start, new_end))
        episodes.append(
            FaultEpisode(
                kind="spike",
                axis=axis,
                onset_index=int(start),
                end_index=int(new_end),
                magnitude_sigmas=float(spike_magnitude_sigmas),
                parameters={"sigma": float(s), "tail": float(spike_tail)},
            )
        )

    # 4) envelope_violation (only if edge_power present)
    if "edge_power" in df.columns:
        env_windows = _choose_windows(
            rng, n_rows, n_episodes_per_kind, envelope_window, min_gap=min_gap,
            forbidden=used_windows,
        )
        s_power = sigmas.get("edge_power", float(np.std(df["edge_power"].to_numpy(), ddof=1)) or 1.0)
        for start, end in env_windows:
            arr = np.array(df["edge_power"].to_numpy(dtype=float), copy=True)
            sign = int(rng.choice([-1, 1]))
            _apply_envelope_violation(arr, start, end, s_power, envelope_magnitude_sigmas, sign)
            df["edge_power"] = arr
            labels[start:end] = 1
            used_windows.append((start, end))
            episodes.append(
                FaultEpisode(
                    kind="envelope_violation",
                    axis="edge_power",
                    onset_index=int(start),
                    end_index=int(end),
                    magnitude_sigmas=float(envelope_magnitude_sigmas),
                    parameters={"sigma": float(s_power), "sign": float(sign)},
                )
            )

    episodes.sort(key=lambda e: e.onset_index)
    knobs = {
        "n_episodes_per_kind": float(n_episodes_per_kind),
        "drift_window": float(drift_window),
        "drift_magnitude_sigmas": float(drift_magnitude_sigmas),
        "stuck_window": float(stuck_window),
        "spike_tail": float(spike_tail),
        "spike_magnitude_sigmas": float(spike_magnitude_sigmas),
        "envelope_window": float(envelope_window),
        "envelope_magnitude_sigmas": float(envelope_magnitude_sigmas),
        "min_gap": float(min_gap),
    }
    return InjectedFaultResult(
        frames=df,
        labels=labels.astype(np.int8),
        episodes=tuple(episodes),
        seed=int(seed),
        knobs=knobs,
    )


__all__ = [
    "DEFAULT_N_EPISODES_PER_KIND",
    "DEFAULT_DRIFT_WINDOW",
    "DEFAULT_DRIFT_END_SIGMAS",
    "DEFAULT_STUCK_WINDOW",
    "DEFAULT_SPIKE_TAIL",
    "DEFAULT_SPIKE_SIGMAS",
    "DEFAULT_ENVELOPE_WINDOW",
    "DEFAULT_ENVELOPE_SIGMAS",
    "DEFAULT_SEED",
    "FAULT_KINDS",
    "INJECTABLE_AXES_DEFAULT",
    "FaultEpisode",
    "InjectedFaultResult",
    "inject_faults",
]
