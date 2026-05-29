"""Pillar A interpretable health baselines (Sprint 28).

Three transparent, classical detectors that establish the bar the Sprint-29 learned
detector must clear. None of these are learned models -- they are fit/score-separated,
deterministic, pure statistics on 2025 auto-mode normal operation:

* :class:`EwmaSpcModel`  -- per-axis EWMA control chart with 3-sigma limits.
* :class:`MahalanobisModel` -- joint-envelope distance in standardised-axis space.
* :class:`PhysicalResidualModel` -- linear residual of ``edge_power`` against
  ``edge_flow`` / ``edge_pump_speed``. Conservatively reports ``low_confidence`` when
  the relationship is too weak to trust rather than fabricating an expectation.

The :class:`HealthBaselineSuite` composes the three into a per-row health score in
``[0, 1]`` plus an ``anomaly_flag`` via documented thresholds, and surfaces the
held-in normal-data false-alarm behaviour -- a Sprint-28 gate artifact.

Hard boundary
-------------
Reads only 2025 auto-mode rows. Before any fit, the input's timestamp keys are run
through the Sprint-27 :func:`assert_holdout_isolated` leakage guard; March-2026 keys
fail loudly. No edge / OT / write-capable connectors are imported or invoked.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from .governance import LOCKED_HOLDOUT_PREFIX, assert_holdout_isolated

# --- shared helpers --------------------------------------------------------

DEFAULT_EWMA_LAMBDA = 0.2
DEFAULT_L_SIGMA = 3.0
DEFAULT_HEALTH_THRESHOLD = 0.5  # health < threshold => anomaly_flag True
DEFAULT_MAHA_CALIB_QUANTILE = 0.995
DEFAULT_RESIDUAL_CALIB_K_SIGMA = 3.0
DEFAULT_RESIDUAL_MIN_R2 = 0.30  # below this we mark low_confidence and emit zeros


def _extract_keys(frames: pd.DataFrame) -> list[str]:
    """Return the string keys we run the leakage guard against.

    Preference order:
      1. a ``timestamp`` column,
      2. the DataFrame index (named or unnamed),
    coerced to strings. Used only for the leakage check; not for scoring.
    """
    if "timestamp" in frames.columns:
        return [str(v) for v in frames["timestamp"].tolist()]
    return [str(v) for v in frames.index.tolist()]


def _assert_isolated(
    frames: pd.DataFrame, *, holdout_prefix: str = LOCKED_HOLDOUT_PREFIX
) -> None:
    """Raise ``LeakageError`` if any input key falls in the locked holdout window."""
    res = assert_holdout_isolated(_extract_keys(frames), holdout_prefix=holdout_prefix)
    if not res.isolated:
        raise LeakageError(
            f"fit input contains {len(res.leaked_keys)} key(s) inside locked holdout "
            f"window '{res.holdout_prefix}': first few = {list(res.leaked_keys[:5])}"
        )


class LeakageError(ValueError):
    """Raised when a fit input contains keys inside the locked March-2026 holdout."""


def _check_axes_present(frames: pd.DataFrame, axes: Sequence[str]) -> None:
    missing = [a for a in axes if a not in frames.columns]
    if missing:
        raise KeyError(f"axes missing from frames: {missing}")


# --- 1) EWMA / SPC ---------------------------------------------------------

@dataclass(frozen=True)
class EwmaSpcModel:
    """Per-axis EWMA control chart fit on 2025 auto-mode normal operation.

    For each axis we store mean ``mu``, std ``sigma``, smoothing factor ``lam``, and
    asymptotic EWMA-statistic standard deviation
    ``sigma_z = sigma * sqrt(lam/(2-lam))``. Control limits are ``mu +/- L*sigma_z``
    with ``L=3``. A per-row score is the EWMA statistic ``z_t``; a per-axis
    anomaly indicator is ``|z_t - mu| > L*sigma_z``.
    """

    axes: tuple[str, ...]
    mu: Mapping[str, float]
    sigma: Mapping[str, float]
    sigma_z: Mapping[str, float]
    upper: Mapping[str, float]
    lower: Mapping[str, float]
    lam: float
    L: float
    n_train_rows: int

    def axis_limits(self) -> dict[str, dict[str, float]]:
        return {
            a: {
                "mu": float(self.mu[a]),
                "sigma": float(self.sigma[a]),
                "sigma_z": float(self.sigma_z[a]),
                "upper": float(self.upper[a]),
                "lower": float(self.lower[a]),
            }
            for a in self.axes
        }

    def score(self, frames: pd.DataFrame) -> pd.DataFrame:
        """Return a DataFrame indexed like ``frames`` with EWMA scores and indicators.

        Columns:
          - ``ewma_<axis>``: the per-axis EWMA statistic z_t,
          - ``flag_<axis>``: 1 if z_t outside [lower, upper] else 0,
          - ``spc_fraction_axes_out``: per-row fraction of axes that tripped,
          - ``spc_max_abs_zscore``: max over axes of ``|z_t - mu| / sigma_z``.
        """
        _check_axes_present(frames, self.axes)
        out = pd.DataFrame(index=frames.index)
        z_cols: list[str] = []
        flag_cols: list[str] = []
        zscore_cols: list[str] = []
        for a in self.axes:
            x = frames[a].to_numpy(dtype=float)
            mu = float(self.mu[a])
            sz = float(self.sigma_z[a])
            up = float(self.upper[a])
            lo = float(self.lower[a])
            # Causal EWMA seeded at mu so the chart starts in-control.
            z = np.empty_like(x)
            prev = mu
            for i, xi in enumerate(x):
                cur = self.lam * xi + (1.0 - self.lam) * prev
                z[i] = cur
                prev = cur
            flag = ((z > up) | (z < lo)).astype(int)
            zscore = np.abs(z - mu) / (sz if sz > 0 else 1.0)
            out[f"ewma_{a}"] = z
            out[f"flag_{a}"] = flag
            out[f"zscore_{a}"] = zscore
            z_cols.append(f"ewma_{a}")
            flag_cols.append(f"flag_{a}")
            zscore_cols.append(f"zscore_{a}")
        flag_matrix = out[flag_cols].to_numpy()
        zscore_matrix = out[zscore_cols].to_numpy()
        out["spc_fraction_axes_out"] = flag_matrix.mean(axis=1)
        out["spc_max_abs_zscore"] = zscore_matrix.max(axis=1) if zscore_matrix.size else 0.0
        return out


def fit_ewma_spc(
    frames: pd.DataFrame,
    axes: Sequence[str],
    lam: float = DEFAULT_EWMA_LAMBDA,
    *,
    L: float = DEFAULT_L_SIGMA,
    holdout_prefix: str = LOCKED_HOLDOUT_PREFIX,
) -> EwmaSpcModel:
    """Fit per-axis EWMA control limits on 2025 auto-mode normal data.

    The leakage guard runs first; March-2026 keys raise :class:`LeakageError`.
    """
    if not 0.0 < lam <= 1.0:
        raise ValueError(f"lam must be in (0, 1]; got {lam}")
    if L <= 0:
        raise ValueError(f"L must be positive; got {L}")
    _assert_isolated(frames, holdout_prefix=holdout_prefix)
    _check_axes_present(frames, axes)
    mu: dict[str, float] = {}
    sigma: dict[str, float] = {}
    sigma_z: dict[str, float] = {}
    upper: dict[str, float] = {}
    lower: dict[str, float] = {}
    for a in axes:
        x = frames[a].to_numpy(dtype=float)
        x = x[np.isfinite(x)]
        if x.size == 0:
            raise ValueError(f"axis {a!r} has no finite values; cannot fit SPC limits")
        m = float(np.mean(x))
        s = float(np.std(x, ddof=1)) if x.size > 1 else 0.0
        sz = s * float(np.sqrt(lam / (2.0 - lam)))
        mu[a] = m
        sigma[a] = s
        sigma_z[a] = sz
        upper[a] = m + L * sz
        lower[a] = m - L * sz
    return EwmaSpcModel(
        axes=tuple(axes),
        mu=mu,
        sigma=sigma,
        sigma_z=sigma_z,
        upper=upper,
        lower=lower,
        lam=float(lam),
        L=float(L),
        n_train_rows=int(len(frames)),
    )


# --- 2) Mahalanobis --------------------------------------------------------

@dataclass(frozen=True)
class MahalanobisModel:
    """Multivariate joint-envelope detector on standardised active-axis vector.

    Fits the mean vector and a ridge-regularised covariance on standardised input.
    Scores return the (non-squared) Mahalanobis distance per row. The suite
    calibrates this to [0, 1] using the train-time 99.5-percentile.
    """

    axes: tuple[str, ...]
    mu: tuple[float, ...]
    sigma: tuple[float, ...]
    cov: tuple[tuple[float, ...], ...]
    cov_inv: tuple[tuple[float, ...], ...]
    ridge: float
    n_train_rows: int
    calib_quantile: float
    calib_distance: float

    def covariance_summary(self) -> dict[str, float]:
        c = np.asarray(self.cov, dtype=float)
        eig = np.linalg.eigvalsh(c)
        return {
            "trace": float(np.trace(c)),
            "det": float(np.linalg.det(c)),
            "min_eig": float(np.min(eig)),
            "max_eig": float(np.max(eig)),
            "condition_number": float(np.max(eig) / max(np.min(eig), 1e-30)),
            "ridge": float(self.ridge),
        }

    def score(self, frames: pd.DataFrame) -> pd.DataFrame:
        """Return per-row Mahalanobis distance and the train-calibrated [0,1] score."""
        _check_axes_present(frames, self.axes)
        X = frames[list(self.axes)].to_numpy(dtype=float)
        mu = np.asarray(self.mu, dtype=float)
        sigma = np.asarray(self.sigma, dtype=float)
        sigma_safe = np.where(sigma > 0, sigma, 1.0)
        Z = (X - mu) / sigma_safe
        Sinv = np.asarray(self.cov_inv, dtype=float)
        # d^2 = z S^-1 z^T per row
        d2 = np.einsum("ij,jk,ik->i", Z, Sinv, Z)
        d2 = np.clip(d2, a_min=0.0, a_max=None)
        d = np.sqrt(d2)
        denom = self.calib_distance if self.calib_distance > 0 else 1.0
        norm = np.clip(d / denom, 0.0, 1.0)
        return pd.DataFrame(
            {"maha_distance": d, "maha_norm_score": norm},
            index=frames.index,
        )


def fit_mahalanobis(
    frames: pd.DataFrame,
    axes: Sequence[str],
    *,
    ridge_eps: float = 1e-6,
    calib_quantile: float = DEFAULT_MAHA_CALIB_QUANTILE,
    holdout_prefix: str = LOCKED_HOLDOUT_PREFIX,
) -> MahalanobisModel:
    """Fit a regularised-covariance Mahalanobis detector on the active-axis vector.

    The leakage guard runs first; March-2026 keys raise :class:`LeakageError`.
    Standardisation uses per-axis ``mu`` / ``sigma`` from the same input (so the
    detector is self-contained; downstream code may still use the cached 2025
    normalisation stats for cross-artifact consistency).
    """
    _assert_isolated(frames, holdout_prefix=holdout_prefix)
    _check_axes_present(frames, axes)
    axes = tuple(axes)
    X = frames[list(axes)].to_numpy(dtype=float)
    if X.shape[0] < max(len(axes) + 2, 4):
        raise ValueError(
            f"need at least {max(len(axes) + 2, 4)} rows to fit Mahalanobis; got {X.shape[0]}"
        )
    mu = X.mean(axis=0)
    sigma = X.std(axis=0, ddof=1)
    sigma_safe = np.where(sigma > 0, sigma, 1.0)
    Z = (X - mu) / sigma_safe
    cov = np.cov(Z, rowvar=False, ddof=1)
    if cov.ndim == 0:
        cov = np.asarray([[float(cov)]])
    k = cov.shape[0]
    # Ridge regularise so the matrix is reliably invertible at small N.
    ridge = float(ridge_eps * (np.trace(cov) / max(k, 1) + 1.0))
    cov_reg = cov + ridge * np.eye(k)
    cov_inv = np.linalg.inv(cov_reg)
    # Calibrate at train time so the [0,1] norm score is reproducible.
    d2_train = np.einsum("ij,jk,ik->i", Z, cov_inv, Z)
    d_train = np.sqrt(np.clip(d2_train, 0.0, None))
    calib = float(np.quantile(d_train, calib_quantile)) if d_train.size else 0.0
    return MahalanobisModel(
        axes=axes,
        mu=tuple(float(v) for v in mu),
        sigma=tuple(float(v) for v in sigma),
        cov=tuple(tuple(float(v) for v in row) for row in cov_reg),
        cov_inv=tuple(tuple(float(v) for v in row) for row in cov_inv),
        ridge=ridge,
        n_train_rows=int(X.shape[0]),
        calib_quantile=float(calib_quantile),
        calib_distance=calib,
    )


# --- 3) Residual vs physical expectation ----------------------------------

# The conservative relationship we fit -- power against flow and pump speed. Affinity
# laws say power scales like Q*H and H depends on speed; over a narrow operating band
# this is reasonably approximated by a linear OLS in (flow, speed). If the fit is
# weak (R^2 below the threshold) we mark the model low_confidence and emit zeros
# rather than fabricate a physical residual signal.
RESIDUAL_TARGET = "edge_power"
RESIDUAL_FEATURES = ("edge_flow", "edge_pump_speed")


@dataclass(frozen=True)
class PhysicalResidualModel:
    target: str
    features: tuple[str, ...]
    intercept: float
    coefficients: tuple[float, ...]
    residual_sigma: float
    r2: float
    high_confidence: bool
    n_train_rows: int
    k_sigma: float = DEFAULT_RESIDUAL_CALIB_K_SIGMA
    reason: str = ""

    @property
    def low_confidence(self) -> bool:
        return not self.high_confidence

    def expectation_summary(self) -> dict[str, float | bool | str | list[float]]:
        return {
            "target": self.target,
            "features": list(self.features),
            "intercept": float(self.intercept),
            "coefficients": [float(c) for c in self.coefficients],
            "residual_sigma": float(self.residual_sigma),
            "r2": float(self.r2),
            "high_confidence": bool(self.high_confidence),
            "low_confidence": bool(self.low_confidence),
            "k_sigma": float(self.k_sigma),
            "reason": self.reason,
        }

    def score(self, frames: pd.DataFrame) -> pd.DataFrame:
        """Return per-row residual and a calibrated [0,1] magnitude score.

        When ``high_confidence`` is False, the magnitude score is forced to 0.0
        across all rows so this baseline never contributes a fabricated signal.
        """
        if not self.high_confidence:
            return pd.DataFrame(
                {
                    "residual": np.zeros(len(frames), dtype=float),
                    "residual_norm_score": np.zeros(len(frames), dtype=float),
                    "residual_high_confidence": np.zeros(len(frames), dtype=int),
                },
                index=frames.index,
            )
        _check_axes_present(frames, [self.target, *self.features])
        X = frames[list(self.features)].to_numpy(dtype=float)
        y = frames[self.target].to_numpy(dtype=float)
        y_hat = self.intercept + X @ np.asarray(self.coefficients, dtype=float)
        resid = y - y_hat
        denom = self.k_sigma * self.residual_sigma if self.residual_sigma > 0 else 1.0
        norm = np.clip(np.abs(resid) / denom, 0.0, 1.0)
        return pd.DataFrame(
            {
                "residual": resid,
                "residual_norm_score": norm,
                "residual_high_confidence": np.ones(len(frames), dtype=int),
            },
            index=frames.index,
        )


def residual_vs_physical(
    frames: pd.DataFrame,
    *,
    target: str = RESIDUAL_TARGET,
    features: Sequence[str] = RESIDUAL_FEATURES,
    min_r2: float = DEFAULT_RESIDUAL_MIN_R2,
    k_sigma: float = DEFAULT_RESIDUAL_CALIB_K_SIGMA,
    holdout_prefix: str = LOCKED_HOLDOUT_PREFIX,
) -> PhysicalResidualModel:
    """Fit a conservative OLS expectation for ``target`` from ``features``.

    Defaults match the documented power-vs-flow-vs-speed relationship. If any
    feature column is missing or the R^2 falls below ``min_r2`` the model is
    returned with ``high_confidence=False`` and ``score()`` emits zeros -- we
    refuse to fabricate a residual signal we don't trust.
    """
    _assert_isolated(frames, holdout_prefix=holdout_prefix)
    features = tuple(features)
    missing = [c for c in (target, *features) if c not in frames.columns]
    if missing:
        return PhysicalResidualModel(
            target=target,
            features=features,
            intercept=0.0,
            coefficients=tuple(0.0 for _ in features),
            residual_sigma=0.0,
            r2=0.0,
            high_confidence=False,
            n_train_rows=int(len(frames)),
            k_sigma=float(k_sigma),
            reason=f"low_confidence: missing columns {missing}",
        )
    X = frames[list(features)].to_numpy(dtype=float)
    y = frames[target].to_numpy(dtype=float)
    mask = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    X = X[mask]
    y = y[mask]
    if X.shape[0] < len(features) + 2:
        return PhysicalResidualModel(
            target=target,
            features=features,
            intercept=0.0,
            coefficients=tuple(0.0 for _ in features),
            residual_sigma=0.0,
            r2=0.0,
            high_confidence=False,
            n_train_rows=int(X.shape[0]),
            k_sigma=float(k_sigma),
            reason="low_confidence: insufficient finite rows",
        )
    X1 = np.concatenate([np.ones((X.shape[0], 1)), X], axis=1)
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    y_hat = X1 @ beta
    resid = y - y_hat
    ss_res = float(np.sum(resid ** 2))
    y_mean = float(np.mean(y))
    ss_tot = float(np.sum((y - y_mean) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    sigma_r = float(np.std(resid, ddof=1)) if resid.size > 1 else 0.0
    high_conf = r2 >= min_r2 and sigma_r > 0.0
    reason = (
        f"high_confidence: r2={r2:.3f} >= min_r2={min_r2}"
        if high_conf
        else f"low_confidence: r2={r2:.3f} < min_r2={min_r2}"
    )
    return PhysicalResidualModel(
        target=target,
        features=features,
        intercept=float(beta[0]),
        coefficients=tuple(float(c) for c in beta[1:]),
        residual_sigma=sigma_r,
        r2=float(r2),
        high_confidence=bool(high_conf),
        n_train_rows=int(X.shape[0]),
        k_sigma=float(k_sigma),
        reason=reason,
    )


# --- 4) Suite --------------------------------------------------------------

@dataclass(frozen=True)
class HealthBaselineSuite:
    """Compose SPC + Mahalanobis + physical residual into one health score.

    Per-row health score is ``1 - clip(mean(component_norm_scores), 0, 1)``. When
    the physical residual is ``low_confidence`` it is excluded from the mean so
    the bar is set by SPC + Mahalanobis only.

    ``anomaly_flag`` = ``health_score < health_threshold``.
    """

    axes: tuple[str, ...]
    spc: EwmaSpcModel
    mahalanobis: MahalanobisModel
    physical_residual: PhysicalResidualModel
    health_threshold: float = DEFAULT_HEALTH_THRESHOLD

    def score(self, frames: pd.DataFrame) -> pd.DataFrame:
        spc = self.spc.score(frames)
        maha = self.mahalanobis.score(frames)
        resid = self.physical_residual.score(frames)
        # Per-row component norms in [0,1].
        spc_norm = spc["spc_fraction_axes_out"].to_numpy(dtype=float)
        maha_norm = maha["maha_norm_score"].to_numpy(dtype=float)
        if self.physical_residual.high_confidence:
            resid_norm = resid["residual_norm_score"].to_numpy(dtype=float)
            combined = (spc_norm + maha_norm + resid_norm) / 3.0
            components_used = 3
        else:
            combined = (spc_norm + maha_norm) / 2.0
            resid_norm = np.zeros_like(spc_norm)
            components_used = 2
        combined = np.clip(combined, 0.0, 1.0)
        health = 1.0 - combined
        flag = (health < self.health_threshold).astype(int)
        out = pd.DataFrame(
            {
                "spc_norm_score": spc_norm,
                "maha_norm_score": maha_norm,
                "residual_norm_score": resid_norm,
                "combined_deviation": combined,
                "health_score": health,
                "anomaly_flag": flag,
                "components_used": np.full(len(frames), components_used, dtype=int),
            },
            index=frames.index,
        )
        return out

    def false_alarm_summary(self, frames: pd.DataFrame) -> dict[str, float | int]:
        """Alarm rate on held-in normal data -- the baseline's own false-alarm bar.

        Reported metrics:
          - ``n_rows``: rows scored,
          - ``spc_any_axis_alarm_rate``: fraction of rows where any axis tripped,
          - ``mahalanobis_alarm_rate``: fraction at or above the train calibration,
          - ``combined_anomaly_flag_rate``: fraction with ``anomaly_flag == 1``,
          - ``health_score_mean`` / ``health_score_p05``.
        """
        spc = self.spc.score(frames)
        maha = self.mahalanobis.score(frames)
        suite = self.score(frames)
        spc_any = (spc["spc_fraction_axes_out"].to_numpy() > 0).astype(int).mean()
        maha_alarm = (
            maha["maha_distance"].to_numpy() >= self.mahalanobis.calib_distance
        ).astype(int).mean()
        flag_rate = float(suite["anomaly_flag"].mean())
        return {
            "n_rows": int(len(frames)),
            "spc_any_axis_alarm_rate": float(spc_any),
            "mahalanobis_alarm_rate": float(maha_alarm),
            "combined_anomaly_flag_rate": float(flag_rate),
            "health_score_mean": float(suite["health_score"].mean()),
            "health_score_p05": float(np.quantile(suite["health_score"], 0.05)),
            "health_threshold": float(self.health_threshold),
        }

    def to_summary_dict(self) -> dict[str, object]:
        """Compact deterministic description of fitted parameters (JSON-safe)."""
        return {
            "axes": list(self.axes),
            "health_threshold": float(self.health_threshold),
            "spc": {
                "lam": self.spc.lam,
                "L": self.spc.L,
                "n_train_rows": self.spc.n_train_rows,
                "axis_limits": self.spc.axis_limits(),
            },
            "mahalanobis": {
                "n_train_rows": self.mahalanobis.n_train_rows,
                "calib_quantile": self.mahalanobis.calib_quantile,
                "calib_distance": self.mahalanobis.calib_distance,
                "covariance_summary": self.mahalanobis.covariance_summary(),
                "ridge": self.mahalanobis.ridge,
            },
            "physical_residual": self.physical_residual.expectation_summary(),
        }


def fit_health_baseline_suite(
    frames: pd.DataFrame,
    axes: Sequence[str],
    *,
    lam: float = DEFAULT_EWMA_LAMBDA,
    L: float = DEFAULT_L_SIGMA,
    calib_quantile: float = DEFAULT_MAHA_CALIB_QUANTILE,
    health_threshold: float = DEFAULT_HEALTH_THRESHOLD,
    holdout_prefix: str = LOCKED_HOLDOUT_PREFIX,
    residual_features: Sequence[str] = RESIDUAL_FEATURES,
    residual_target: str = RESIDUAL_TARGET,
    residual_min_r2: float = DEFAULT_RESIDUAL_MIN_R2,
) -> HealthBaselineSuite:
    """One-shot fit of all three baselines. Asserts holdout isolation up front."""
    _assert_isolated(frames, holdout_prefix=holdout_prefix)
    spc = fit_ewma_spc(frames, axes, lam=lam, L=L, holdout_prefix=holdout_prefix)
    maha = fit_mahalanobis(
        frames, axes, calib_quantile=calib_quantile, holdout_prefix=holdout_prefix
    )
    resid = residual_vs_physical(
        frames,
        target=residual_target,
        features=residual_features,
        min_r2=residual_min_r2,
        holdout_prefix=holdout_prefix,
    )
    return HealthBaselineSuite(
        axes=tuple(axes),
        spc=spc,
        mahalanobis=maha,
        physical_residual=resid,
        health_threshold=float(health_threshold),
    )


__all__ = [
    "DEFAULT_EWMA_LAMBDA",
    "DEFAULT_L_SIGMA",
    "DEFAULT_HEALTH_THRESHOLD",
    "DEFAULT_MAHA_CALIB_QUANTILE",
    "DEFAULT_RESIDUAL_CALIB_K_SIGMA",
    "DEFAULT_RESIDUAL_MIN_R2",
    "RESIDUAL_TARGET",
    "RESIDUAL_FEATURES",
    "LeakageError",
    "EwmaSpcModel",
    "MahalanobisModel",
    "PhysicalResidualModel",
    "HealthBaselineSuite",
    "fit_ewma_spc",
    "fit_mahalanobis",
    "residual_vs_physical",
    "fit_health_baseline_suite",
]
