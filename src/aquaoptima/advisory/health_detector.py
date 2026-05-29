"""Pillar A learned health detector (Sprint 29).

A small CPU-friendly autoencoder over the standardised active-axis vector. Trained
ONLY on 2025 auto-mode normal data; reconstruction error is the per-row anomaly
score. Sprint-27 leakage guard runs before any fit, March-2026 keys raise
:class:`LeakageError`.

This detector is the LEARNED candidate that must clear the bar set by the Sprint-28
interpretable baselines (EWMA/SPC + Mahalanobis + physical residual). Whether it
clears the bar is decided empirically by :mod:`aquaoptima.advisory.health_gate`,
not by this module.

Hard boundary
-------------
* Offline-only; no edge / write-capable connector imports.
* Deterministic: same seed + same data => bit-identical fitted parameters and
  bit-identical per-row scores (asserted by the test suite).
* Fit/score separated: ``fit_health_detector`` returns a frozen
  :class:`FittedHealthDetector`; scoring is a pure forward pass.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
import torch
from torch import nn

from .governance import LOCKED_HOLDOUT_PREFIX, assert_holdout_isolated
from .health_baselines import LeakageError, _check_axes_present, _extract_keys

DEFAULT_HIDDEN_DIM = 16
DEFAULT_LATENT_DIM = 8
DEFAULT_EPOCHS = 60
DEFAULT_BATCH_SIZE = 256
DEFAULT_LEARNING_RATE = 1e-3
DEFAULT_WEIGHT_DECAY = 1e-5
DEFAULT_CALIB_QUANTILE = 0.995
DEFAULT_FLAG_QUANTILE = 0.99
DEFAULT_VAL_FRACTION = 0.2
DEFAULT_SEED = 0


# --------------------------------------------------------------------------- #
# torch model
# --------------------------------------------------------------------------- #
class HealthAutoencoder(nn.Module):
    """Small symmetric MLP autoencoder over the standardised axis vector.

    Architecture: ``n_axes -> hidden -> latent -> hidden -> n_axes`` with ``Tanh``
    activations between linear layers. Deterministic initialisation via the
    ``seed`` argument; all parameters live on CPU.
    """

    def __init__(
        self,
        n_axes: int,
        *,
        hidden_dim: int = DEFAULT_HIDDEN_DIM,
        latent_dim: int = DEFAULT_LATENT_DIM,
        seed: int = DEFAULT_SEED,
    ) -> None:
        super().__init__()
        if n_axes <= 0:
            raise ValueError(f"n_axes must be positive; got {n_axes}")
        if latent_dim <= 0 or hidden_dim <= 0:
            raise ValueError("hidden_dim and latent_dim must be positive")
        gen = torch.Generator(device="cpu")
        gen.manual_seed(int(seed))
        self.n_axes = int(n_axes)
        self.hidden_dim = int(hidden_dim)
        self.latent_dim = int(latent_dim)
        self.encoder = nn.Sequential(
            nn.Linear(n_axes, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, latent_dim),
            nn.Tanh(),
        )
        self.decoder = nn.Sequential(
            nn.Linear(latent_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, n_axes),
        )
        # Seed-controlled init so determinism does not depend on global torch state.
        for m in self.modules():
            if isinstance(m, nn.Linear):
                # Xavier-uniform sampled from the local generator
                fan_in = m.weight.shape[1]
                fan_out = m.weight.shape[0]
                bound = float((6.0 / (fan_in + fan_out)) ** 0.5)
                w = torch.empty(
                    m.weight.shape, dtype=torch.float32
                ).uniform_(-bound, bound, generator=gen)
                with torch.no_grad():
                    m.weight.copy_(w)
                    m.bias.zero_()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = self.encoder(x)
        return self.decoder(z)


# --------------------------------------------------------------------------- #
# normalization helpers
# --------------------------------------------------------------------------- #
def _load_frozen_norm_stats(path: Path) -> dict[str, dict[str, float]]:
    """Load the cached 2025 train-stats JSON; returns ``{axis: {mu, sigma}}``."""
    text = Path(path).read_text()
    payload = json.loads(text)
    stats = payload.get("stats", {})
    out: dict[str, dict[str, float]] = {}
    for axis, blk in stats.items():
        out[axis] = {"mu": float(blk["mu"]), "sigma": float(blk["sigma"])}
    return out


def _resolve_norm_stats(
    axes: Sequence[str],
    frames: pd.DataFrame,
    explicit: Mapping[str, Mapping[str, float]] | None,
    stats_path: Path | str | None,
) -> tuple[np.ndarray, np.ndarray, str]:
    """Resolve per-axis ``mu`` / ``sigma`` from explicit map, JSON file, or input.

    Priority: explicit mapping > stats_path > input-frame statistics. The third
    fallback is for test fixtures and synthetic data; production code paths should
    pass either ``explicit`` or ``stats_path`` so standardisation uses the frozen
    2025 stats.
    """
    if explicit is not None:
        missing = [a for a in axes if a not in explicit]
        if missing:
            raise KeyError(f"axes missing from norm_stats: {missing}")
        mu = np.array([float(explicit[a]["mu"]) for a in axes], dtype=np.float64)
        sigma = np.array([float(explicit[a]["sigma"]) for a in axes], dtype=np.float64)
        return mu, sigma, "explicit_mapping"
    if stats_path is not None:
        loaded = _load_frozen_norm_stats(Path(stats_path))
        missing = [a for a in axes if a not in loaded]
        if missing:
            raise KeyError(f"axes missing from stats file: {missing}")
        mu = np.array([loaded[a]["mu"] for a in axes], dtype=np.float64)
        sigma = np.array([loaded[a]["sigma"] for a in axes], dtype=np.float64)
        return mu, sigma, str(stats_path)
    X = frames[list(axes)].to_numpy(dtype=np.float64)
    mu = X.mean(axis=0)
    sigma = X.std(axis=0, ddof=1)
    return mu, sigma, "input_frames"


def _standardise(X: np.ndarray, mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    sigma_safe = np.where(sigma > 0, sigma, 1.0)
    return (X - mu) / sigma_safe


# --------------------------------------------------------------------------- #
# Fitted detector
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FittedHealthDetector:
    """Frozen autoencoder + standardisation + reconstruction-error calibration."""

    axes: tuple[str, ...]
    mu: tuple[float, ...]
    sigma: tuple[float, ...]
    state_dict: Mapping[str, torch.Tensor]
    hidden_dim: int
    latent_dim: int
    seed: int
    epochs: int
    batch_size: int
    learning_rate: float
    weight_decay: float
    norm_source: str
    n_train_rows: int
    n_val_rows: int
    train_error_p995: float
    val_error_p995: float
    flag_threshold_error: float
    train_final_loss: float
    val_final_loss: float

    def _build_model(self) -> HealthAutoencoder:
        model = HealthAutoencoder(
            n_axes=len(self.axes),
            hidden_dim=self.hidden_dim,
            latent_dim=self.latent_dim,
            seed=self.seed,
        )
        model.load_state_dict({k: v.clone() for k, v in self.state_dict.items()})
        model.eval()
        return model

    def reconstruct(self, frames: pd.DataFrame) -> np.ndarray:
        """Return per-row reconstruction error (unnormalised)."""
        _check_axes_present(frames, list(self.axes))
        X = frames[list(self.axes)].to_numpy(dtype=np.float64)
        mu = np.asarray(self.mu, dtype=np.float64)
        sigma = np.asarray(self.sigma, dtype=np.float64)
        Z = _standardise(X, mu, sigma).astype(np.float32)
        model = self._build_model()
        with torch.no_grad():
            t = torch.from_numpy(Z)
            y = model(t).numpy()
        err = np.mean((Z - y) ** 2, axis=1)
        return err.astype(np.float64)

    def score(self, frames: pd.DataFrame) -> pd.DataFrame:
        """Return per-row reconstruction error, normalised score, and binary flag.

        Columns:
          * ``detector_recon_error``: raw MSE per row over the standardised axes.
          * ``detector_anomaly_score``: ``clip(err / calib_error, 0, 1)``.
            Higher = more anomalous.
          * ``detector_flag``: 1 iff ``err >= flag_threshold_error`` else 0.
        """
        err = self.reconstruct(frames)
        denom = self.val_error_p995 if self.val_error_p995 > 0 else self.train_error_p995
        denom = denom if denom > 0 else 1.0
        norm = np.clip(err / denom, 0.0, 1.0)
        flag = (err >= self.flag_threshold_error).astype(int)
        return pd.DataFrame(
            {
                "detector_recon_error": err,
                "detector_anomaly_score": norm,
                "detector_flag": flag,
            },
            index=frames.index,
        )

    def to_summary_dict(self) -> dict[str, object]:
        return {
            "axes": list(self.axes),
            "architecture": {
                "n_axes": len(self.axes),
                "hidden_dim": int(self.hidden_dim),
                "latent_dim": int(self.latent_dim),
                "activation": "tanh",
                "layout": "n_axes -> hidden -> latent -> hidden -> n_axes",
            },
            "training": {
                "seed": int(self.seed),
                "epochs": int(self.epochs),
                "batch_size": int(self.batch_size),
                "learning_rate": float(self.learning_rate),
                "weight_decay": float(self.weight_decay),
                "n_train_rows": int(self.n_train_rows),
                "n_val_rows": int(self.n_val_rows),
                "train_final_loss": float(self.train_final_loss),
                "val_final_loss": float(self.val_final_loss),
                "norm_source": self.norm_source,
            },
            "calibration": {
                "train_error_p995": float(self.train_error_p995),
                "val_error_p995": float(self.val_error_p995),
                "flag_threshold_error": float(self.flag_threshold_error),
                "flag_quantile": float(DEFAULT_FLAG_QUANTILE),
            },
        }


# --------------------------------------------------------------------------- #
# fit
# --------------------------------------------------------------------------- #
def _deterministic_seed(seed: int) -> torch.Generator:
    """Set per-call generator + numpy seed; do NOT alter torch global state durably."""
    torch.manual_seed(int(seed))
    np.random.seed(int(seed))
    gen = torch.Generator(device="cpu")
    gen.manual_seed(int(seed))
    return gen


def fit_health_detector(
    frames: pd.DataFrame,
    axes: Sequence[str],
    *,
    seed: int = DEFAULT_SEED,
    epochs: int = DEFAULT_EPOCHS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    learning_rate: float = DEFAULT_LEARNING_RATE,
    weight_decay: float = DEFAULT_WEIGHT_DECAY,
    hidden_dim: int = DEFAULT_HIDDEN_DIM,
    latent_dim: int = DEFAULT_LATENT_DIM,
    val_fraction: float = DEFAULT_VAL_FRACTION,
    calib_quantile: float = DEFAULT_CALIB_QUANTILE,
    flag_quantile: float = DEFAULT_FLAG_QUANTILE,
    norm_stats: Mapping[str, Mapping[str, float]] | None = None,
    norm_stats_path: Path | str | None = None,
    holdout_prefix: str = LOCKED_HOLDOUT_PREFIX,
) -> FittedHealthDetector:
    """Fit the autoencoder on 2025 normal data.

    Steps:
      1. Run the Sprint-27 leakage guard on the input keys; March-2026 keys raise.
      2. Resolve standardisation stats (explicit mapping, JSON path, or input frames).
      3. Standardise inputs.
      4. Deterministic train/val split (no shuffling so the split survives seed
         changes to the optimiser).
      5. Train an MLP autoencoder with seeded Adam on full mini-batches.
      6. Calibrate the per-row reconstruction-error quantiles on the held-in
         normal val split.

    Determinism: identical ``seed + data + hyperparameters`` produce bit-identical
    parameters and bit-identical per-row scores (asserted in the test suite).
    """
    if not 0.0 < val_fraction < 1.0:
        raise ValueError(f"val_fraction must be in (0, 1); got {val_fraction}")
    if epochs <= 0:
        raise ValueError(f"epochs must be positive; got {epochs}")
    if batch_size <= 0:
        raise ValueError(f"batch_size must be positive; got {batch_size}")

    keys = _extract_keys(frames)
    res = assert_holdout_isolated(keys, holdout_prefix=holdout_prefix)
    if not res.isolated:
        raise LeakageError(
            f"fit_health_detector input contains {len(res.leaked_keys)} key(s) "
            f"inside locked holdout window '{res.holdout_prefix}': "
            f"first few = {list(res.leaked_keys[:5])}"
        )
    _check_axes_present(frames, list(axes))
    axes_t = tuple(axes)

    mu_arr, sigma_arr, norm_source = _resolve_norm_stats(
        axes_t, frames, norm_stats, norm_stats_path
    )

    X = frames[list(axes_t)].to_numpy(dtype=np.float64)
    finite_mask = np.all(np.isfinite(X), axis=1)
    if not finite_mask.all():
        X = X[finite_mask]
    Z = _standardise(X, mu_arr, sigma_arr).astype(np.float32)
    n_total = Z.shape[0]
    min_train_rows = max(8, len(axes_t) * 4)
    if n_total < min_train_rows:
        raise ValueError(
            f"need at least {min_train_rows} finite training rows; got {n_total}"
        )
    n_val = max(2, int(round(n_total * val_fraction)))
    n_train = n_total - n_val
    if n_train < max(4, len(axes_t)):
        raise ValueError(
            f"insufficient training rows after val split: train={n_train}, val={n_val}"
        )
    train_Z = Z[:n_train]
    val_Z = Z[n_train:]

    # Deterministic seeding for both numpy and torch.
    _deterministic_seed(seed)
    model = HealthAutoencoder(
        n_axes=len(axes_t),
        hidden_dim=hidden_dim,
        latent_dim=latent_dim,
        seed=seed,
    )
    model.train()
    optimizer = torch.optim.Adam(
        model.parameters(), lr=float(learning_rate), weight_decay=float(weight_decay)
    )
    loss_fn = nn.MSELoss(reduction="mean")
    train_tensor = torch.from_numpy(train_Z)
    val_tensor = torch.from_numpy(val_Z)

    # Deterministic batch order: shuffled with a seeded numpy RNG, no torch DataLoader.
    rng = np.random.default_rng(int(seed))
    n_batches = max(1, int(np.ceil(n_train / batch_size)))
    train_final_loss = float("nan")
    for epoch in range(int(epochs)):
        order = rng.permutation(n_train)
        epoch_losses: list[float] = []
        for b in range(n_batches):
            idx = order[b * batch_size : (b + 1) * batch_size]
            if idx.size == 0:
                continue
            batch = train_tensor[torch.from_numpy(idx.astype(np.int64))]
            optimizer.zero_grad(set_to_none=True)
            recon = model(batch)
            loss = loss_fn(recon, batch)
            loss.backward()
            optimizer.step()
            epoch_losses.append(float(loss.item()))
        train_final_loss = float(np.mean(epoch_losses)) if epoch_losses else float("nan")

    model.eval()
    with torch.no_grad():
        train_recon = model(train_tensor).numpy()
        val_recon = model(val_tensor).numpy()
    train_err = np.mean((train_Z - train_recon) ** 2, axis=1)
    val_err = np.mean((val_Z - val_recon) ** 2, axis=1)
    train_p995 = float(np.quantile(train_err, calib_quantile)) if train_err.size else 0.0
    val_p995 = float(np.quantile(val_err, calib_quantile)) if val_err.size else 0.0
    flag_threshold = (
        float(np.quantile(val_err, flag_quantile)) if val_err.size else train_p995
    )
    val_final_loss = float(np.mean(val_err)) if val_err.size else float("nan")

    # Snapshot the state_dict on CPU as detached, contiguous tensors so the dataclass
    # is hashable-friendly and the saved values can be diffed for determinism.
    state_dict = {
        k: v.detach().clone().contiguous().to(torch.float32) for k, v in model.state_dict().items()
    }

    return FittedHealthDetector(
        axes=axes_t,
        mu=tuple(float(v) for v in mu_arr),
        sigma=tuple(float(v) for v in sigma_arr),
        state_dict=state_dict,
        hidden_dim=int(hidden_dim),
        latent_dim=int(latent_dim),
        seed=int(seed),
        epochs=int(epochs),
        batch_size=int(batch_size),
        learning_rate=float(learning_rate),
        weight_decay=float(weight_decay),
        norm_source=norm_source,
        n_train_rows=int(n_train),
        n_val_rows=int(n_val),
        train_error_p995=train_p995,
        val_error_p995=val_p995,
        flag_threshold_error=float(flag_threshold),
        train_final_loss=float(train_final_loss),
        val_final_loss=float(val_final_loss),
    )


__all__ = [
    "DEFAULT_HIDDEN_DIM",
    "DEFAULT_LATENT_DIM",
    "DEFAULT_EPOCHS",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_LEARNING_RATE",
    "DEFAULT_WEIGHT_DECAY",
    "DEFAULT_CALIB_QUANTILE",
    "DEFAULT_FLAG_QUANTILE",
    "DEFAULT_VAL_FRACTION",
    "DEFAULT_SEED",
    "HealthAutoencoder",
    "FittedHealthDetector",
    "fit_health_detector",
]
