"""dPHM TCN training loop (AOPSO Sprint 24).

Offline training orchestration for :class:`aquaoptima.models.tcn_dphm.TCN_DPHM`
over the Sprint 23 Yilan splits/normalization, with:

* AdamW optimizer,
* ``ReduceLROnPlateau`` (patience=5, factor=0.5) on val loss,
* early stopping (patience=10 on val loss),
* checkpointing: ``model_best.pt`` (lowest val loss), ``model_final.pt``,
  ``training_log.csv`` (epoch, train_loss, val_loss, lr, timestamp), and a copy
  of the normalization stats JSON, all under ``--checkpoint-dir``
  (default ``data/models/yilan_dphm_v1/``).

Determinism: seeds are set via :func:`aquaoptima.training.seed`, and the
training DataLoader shuffles with a seeded ``torch.Generator`` so two identical
CPU runs produce bitwise-identical ``model_final.pt``.

``--subset-rows`` caps the number of *windows* used per split so smoke/CI runs
finish in seconds. The underlying dataset still loads the full CSV because the
train/val rows live at high CSV row indices; capping windows (not CSV rows)
keeps a usable, contiguous slice of real windows.

Safety: offline only; reads static CSV-derived splits; writes only checkpoints
under ``data/models/``; produces NO advisory/control output; ``.pt`` state_dict
only; NO ONNX export; no edge imports; no network egress.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import time
from pathlib import Path
from typing import Iterable

import torch
from torch.utils.data import DataLoader, Subset

from ..dataio.yilan_timeseries_dataset import YilanTimeSeriesDataset
from ..training.normalization import load_stats
from ..models.tcn_dphm import TCN_DPHM
from .dphm_loss import MultiAxisLoss
from .seed import set_deterministic_seed

__all__ = ["train", "main", "load_config"]

DEFAULT_CHECKPOINT_DIR = "data/models/yilan_dphm_v1"


def load_config(path: str | None) -> dict:
    if not path:
        return {}
    import yaml

    return yaml.safe_load(Path(path).read_text()) or {}


def _cap_subset(dataset, subset_rows: int | None):
    """Cap a dataset to its first ``subset_rows`` windows (deterministic)."""
    if subset_rows is None or subset_rows >= len(dataset):
        return dataset
    n = max(1, int(subset_rows))
    n = min(n, len(dataset))
    return Subset(dataset, list(range(n)))


def _run_epoch(model, loader, loss_fn, optimizer, train: bool) -> float:
    model.train(train)
    total = 0.0
    count = 0
    ctx = torch.enable_grad() if train else torch.no_grad()
    with ctx:
        for x, y in loader:
            pred = model(x)
            loss = loss_fn(pred, y)
            if train:
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
            bs = x.shape[0]
            total += float(loss.detach()) * bs
            count += bs
    return total / max(1, count)


def train(
    *,
    config: dict | None = None,
    split_manifest: str = "data/splits/yilan_2025_split_v1.json",
    norm_stats: str = "data/normalization/yilan_2025_train_stats.json",
    epochs: int = 2,
    batch_size: int = 128,
    lr: float = 1e-3,
    subset_rows: int | None = None,
    checkpoint_dir: str = DEFAULT_CHECKPOINT_DIR,
    csv_path: str | None = None,
    target_mode: str | None = None,
    horizon: int | None = None,
    verbose: bool = True,
) -> dict:
    """Run the training loop and write checkpoints. Returns a result dict.

    Sprint 26 adds ``target_mode`` (``"residual"`` default, ``"absolute"`` for
    comparison) and ``horizon`` (steps-ahead; 60s cadence so steps==minutes).
    Both fall back to the config ``data`` block, then to residual / h=1.
    """
    cfg = config or {}
    mcfg = cfg.get("model", {})
    dcfg = cfg.get("data", {})
    tcfg = cfg.get("train", {})
    scfg = (tcfg.get("scheduler") or {})
    escfg = (tcfg.get("early_stopping") or {})
    seed_cfg = cfg.get("seed", {})

    set_deterministic_seed(
        torch_seed=int(seed_cfg.get("torch_seed", 42)),
        numpy_seed=int(seed_cfg.get("numpy_seed", 42)),
        random_seed=int(seed_cfg.get("random_seed", 42)),
    )

    window = int(dcfg.get("window", 10))
    horizon = int(horizon if horizon is not None else dcfg.get("horizon", 1))
    stride = int(dcfg.get("stride", 1))
    # Sprint 26: residual-over-persistence target by default. Overridable via
    # config (data.target_mode) or the ``target_mode`` argument.
    target_mode = str(target_mode or dcfg.get("target_mode", "residual"))
    channels = int(mcfg.get("channels", 32))
    kernel_size = int(mcfg.get("kernel_size", 3))
    dropout = float(mcfg.get("dropout", 0.0))
    weight_decay = float(tcfg.get("weight_decay", 1e-4))
    sched_patience = int(scfg.get("patience", 5))
    sched_factor = float(scfg.get("factor", 0.5))
    es_patience = int(escfg.get("patience", 10))

    stats = load_stats(norm_stats)
    active_axes = list(stats["active_axes"])

    train_ds = YilanTimeSeriesDataset.from_paths(
        split_manifest,
        norm_stats,
        split_key="train",
        window=window,
        horizon=horizon,
        stride=stride,
        target_mode=target_mode,
        csv_path=csv_path,
    )
    val_ds = YilanTimeSeriesDataset.from_paths(
        split_manifest,
        norm_stats,
        split_key="val",
        window=window,
        horizon=horizon,
        stride=stride,
        target_mode=target_mode,
        csv_path=csv_path,
    )

    train_ds = _cap_subset(train_ds, subset_rows)
    val_ds = _cap_subset(val_ds, subset_rows)

    # Seeded generator so shuffling is deterministic across identical runs.
    gen = torch.Generator()
    gen.manual_seed(int(seed_cfg.get("torch_seed", 42)))
    train_loader = DataLoader(
        train_ds, batch_size=batch_size, shuffle=True, generator=gen, drop_last=False
    )
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False)

    model = TCN_DPHM.from_norm_stats(
        stats, channels=channels, kernel_size=kernel_size, dropout=dropout
    )
    loss_fn = MultiAxisLoss(active_axes)

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", patience=sched_patience, factor=sched_factor
    )

    ckpt = Path(checkpoint_dir)
    ckpt.mkdir(parents=True, exist_ok=True)
    log_path = ckpt / "training_log.csv"
    best_path = ckpt / "model_best.pt"
    final_path = ckpt / "model_final.pt"
    stats_copy = ckpt / "normalization_stats.json"
    shutil.copyfile(norm_stats, stats_copy)
    # Sprint 26: persist run metadata (target_mode/horizon) so eval can decode
    # residual-vs-absolute predictions correctly without re-guessing.
    (ckpt / "run_meta.json").write_text(
        json.dumps(
            {
                "target_mode": target_mode,
                "horizon": horizon,
                "window": window,
                "stride": stride,
                "active_axes": active_axes,
            },
            indent=2,
        )
        + "\n"
    )

    log_rows: list[dict] = []
    best_val = float("inf")
    epochs_since_improve = 0
    train_losses: list[float] = []
    val_losses: list[float] = []

    for epoch in range(1, epochs + 1):
        train_loss = _run_epoch(model, train_loader, loss_fn, optimizer, train=True)
        val_loss = _run_epoch(model, val_loader, loss_fn, optimizer, train=False)

        # STOP-condition guard: never checkpoint a divergent model.
        if not (torch.isfinite(torch.tensor(train_loss)) and
                torch.isfinite(torch.tensor(val_loss))):
            raise RuntimeError(
                f"non-finite loss at epoch {epoch}: "
                f"train={train_loss} val={val_loss}"
            )

        scheduler.step(val_loss)
        cur_lr = optimizer.param_groups[0]["lr"]

        train_losses.append(train_loss)
        val_losses.append(val_loss)
        log_rows.append(
            {
                "epoch": epoch,
                "train_loss": f"{train_loss:.6f}",
                "val_loss": f"{val_loss:.6f}",
                "lr": f"{cur_lr:.6e}",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        )

        improved = val_loss < best_val
        if improved:
            best_val = val_loss
            epochs_since_improve = 0
            torch.save(model.state_dict(), best_path)
        else:
            epochs_since_improve += 1

        if verbose:
            print(
                f"epoch {epoch} | train_loss {train_loss:.6f} | "
                f"val_loss {val_loss:.6f} | lr {cur_lr:.1e}"
                + ("  (best)" if improved else "")
            )

        if epochs_since_improve >= es_patience:
            if verbose:
                print(f"early stopping at epoch {epoch} (no val improvement)")
            break

    # Always write final weights (state_dict only -- inert .pt, no ONNX).
    torch.save(model.state_dict(), final_path)

    # If val never improved (e.g. inf), still ensure model_best exists.
    if not best_path.exists():
        torch.save(model.state_dict(), best_path)

    with log_path.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["epoch", "train_loss", "val_loss", "lr", "timestamp"]
        )
        writer.writeheader()
        writer.writerows(log_rows)

    if verbose:
        print(f"saved best checkpoint -> {best_path}")
        print(f"saved final checkpoint -> {final_path}")

    return {
        "train_losses": train_losses,
        "val_losses": val_losses,
        "best_val_loss": best_val,
        "best_path": str(best_path),
        "final_path": str(final_path),
        "log_path": str(log_path),
        "stats_copy": str(stats_copy),
        "n_features": model.n_features,
        "n_axes": model.n_axes,
        "active_axes": active_axes,
        "target_mode": target_mode,
        "horizon": horizon,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AOPSO Sprint 24 dPHM TCN trainer")
    parser.add_argument("--config", default="configs/yilan_dphm_v1.yaml")
    parser.add_argument(
        "--split-manifest", default="data/splits/yilan_2025_split_v1.json"
    )
    parser.add_argument(
        "--norm-stats", default="data/normalization/yilan_2025_train_stats.json"
    )
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--lr", type=float, default=None)
    parser.add_argument("--subset-rows", type=int, default=None)
    parser.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR)
    parser.add_argument("--csv-path", default=None)
    parser.add_argument(
        "--target-mode",
        default=None,
        choices=["residual", "absolute", None],
        help="Prediction target: 'residual' (Sprint 26 default) or 'absolute'.",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=None,
        help="Steps ahead (60s cadence -> steps == minutes). Default config/h=1.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    cfg = load_config(args.config)
    tcfg = cfg.get("train", {})

    epochs = args.epochs if args.epochs is not None else int(tcfg.get("epochs", 2))
    batch_size = (
        args.batch_size
        if args.batch_size is not None
        else int(tcfg.get("batch_size", 128))
    )
    lr = args.lr if args.lr is not None else float(tcfg.get("lr", 1e-3))

    train(
        config=cfg,
        split_manifest=args.split_manifest,
        norm_stats=args.norm_stats,
        epochs=epochs,
        batch_size=batch_size,
        lr=lr,
        subset_rows=args.subset_rows,
        checkpoint_dir=args.checkpoint_dir,
        csv_path=args.csv_path,
        target_mode=args.target_mode,
        horizon=args.horizon,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
