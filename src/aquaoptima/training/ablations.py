"""Ablation harness for sensor-only vs sensor-plus-physics training.

Both modes share the same model architecture, optimizer, dataset,
seed, and number of training iterations — the only difference is the
physics-loss weight schedule:

* ``sensor_only`` — ``lambda_physics`` fixed at 0.0; only the masked
  supervised loss drives gradients.
* ``sensor_plus_physics`` — ``lambda_physics`` follows the configured
  scheduler (defaults to a small constant, but :class:`LinearRampLambda`
  is supported via ``lambda_physics_schedule``); both loss terms drive
  gradients.

Sprint 5 added:

* ``fixture`` selector (``branch`` / ``single_loop`` / ``pump``).
* ``data`` selector (``physics_consistent`` / ``shape_only``).
* Per-mode lambda scheduler overrides so callers can wire in a
  :class:`LinearRampLambda` warmup without rewriting the harness.

The harness returns a dict ``{mode, summary, history}`` so callers can
compare runs without re-running training to recompute aggregates.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import torch

from aquaoptima.dataio import WindowDataset, generate_synthetic_telemetry
from aquaoptima.dataio.telemetry import generate_physics_consistent_telemetry
from aquaoptima.dphm import (
    Network,
    make_branch_network,
    make_grid_network,
    make_pump_network,
    make_single_loop_network,
)
from aquaoptima.models import DPHMPINN
from aquaoptima.models.lambda_scheduler import FixedLambda, LambdaScheduler
from aquaoptima.topology import build_graph_features, sensor_mask_from_indices

from .train import TrainConfig, train_loop


ABLATION_MODES = ("sensor_only", "sensor_plus_physics")
FIXTURES = ("branch", "single_loop", "pump", "grid")
DATA_KINDS = ("physics_consistent", "shape_only")


# Sprint 8 default grid: 7 rows x 8 cols -> 56 nodes / 97 edges. Sits
# inside the O(50-200) target range while keeping CPU runtime bounded.
_GRID_DEFAULT_ROWS = 7
_GRID_DEFAULT_COLS = 8


def _make_grid_default() -> Network:
    return make_grid_network(
        rows=_GRID_DEFAULT_ROWS, cols=_GRID_DEFAULT_COLS, seed=0
    )


_FIXTURE_BUILDERS = {
    "branch": make_branch_network,
    "single_loop": make_single_loop_network,
    "pump": make_pump_network,
    "grid": _make_grid_default,
}

# Per-fixture default sensor masks. We always observe the reservoir
# (a SCADA pressure transducer is realistic there) plus one downstream
# node so the supervised loss has a non-empty target set. For the grid
# fixture we observe the reservoir corner, an interior node, and the
# opposite corner so the supervised target spans the mesh.
_GRID_DEFAULT_N = _GRID_DEFAULT_ROWS * _GRID_DEFAULT_COLS
_FIXTURE_SENSOR_INDICES = {
    "branch": [0, 2],
    "single_loop": [0, 2],
    "pump": [0, 2],
    "grid": [0, _GRID_DEFAULT_N // 2, _GRID_DEFAULT_N - 1],
}


def _build_fixture(fixture: str) -> tuple[Network, list[int]]:
    if fixture not in _FIXTURE_BUILDERS:
        raise ValueError(
            f"unknown fixture {fixture!r}; valid fixtures: {FIXTURES}"
        )
    return _FIXTURE_BUILDERS[fixture](), _FIXTURE_SENSOR_INDICES[fixture]


def _build_dataset(
    network: Network,
    *,
    data: str,
    num_steps: int,
    seed: int,
    window: int,
) -> WindowDataset:
    if data == "physics_consistent":
        series = generate_physics_consistent_telemetry(
            network, num_steps=num_steps, seed=seed, window=window
        )
    elif data == "shape_only":
        series = generate_synthetic_telemetry(
            network, num_steps=num_steps, seed=seed, window=window
        )
    else:
        raise ValueError(
            f"unknown data kind {data!r}; valid kinds: {DATA_KINDS}"
        )
    return WindowDataset(series, window=window)


def _lambdas_for_mode(
    mode: str,
    lambda_data_value: float,
    lambda_physics_value: float,
    lambda_data_schedule: Optional[LambdaScheduler],
    lambda_physics_schedule: Optional[LambdaScheduler],
) -> tuple[LambdaScheduler, LambdaScheduler]:
    if mode == "sensor_only":
        ld = lambda_data_schedule or FixedLambda(lambda_data_value)
        return ld, FixedLambda(0.0)
    if mode == "sensor_plus_physics":
        ld = lambda_data_schedule or FixedLambda(lambda_data_value)
        lp = lambda_physics_schedule or FixedLambda(lambda_physics_value)
        return ld, lp
    raise ValueError(
        f"unknown ablation mode {mode!r}; valid modes: {ABLATION_MODES}"
    )


def run_ablation(
    *,
    mode: str,
    num_iterations: int,
    seed: int,
    fixture: str = "branch",
    data: str = "physics_consistent",
    hidden_dim: int = 16,
    lr: float = 1e-3,
    lambda_data_value: float = 1.0,
    lambda_physics_value: float = 1e-4,
    lambda_data_schedule: Optional[LambdaScheduler] = None,
    lambda_physics_schedule: Optional[LambdaScheduler] = None,
    num_steps: int = 40,
    window: int = 32,
    batch_size: int = 1,
) -> dict[str, Any]:
    """Run one ablation arm end-to-end and return its metrics dict.

    Parameters
    ----------
    mode
        Either ``"sensor_only"`` or ``"sensor_plus_physics"``.
    num_iterations
        Number of training steps to take.
    seed
        Master seed for torch RNG and the telemetry generator.
    fixture
        One of ``"branch"``, ``"single_loop"``, ``"pump"`` — selects the
        Sprint 2 network fixture used both for data generation and as the
        physics residual reference.
    data
        Telemetry source. ``"physics_consistent"`` (default) routes
        through :func:`generate_physics_consistent_telemetry` so every
        sample satisfies the dPHM residual; ``"shape_only"`` falls back
        to the legacy shape-only generator (used by some pre-Sprint-5
        tests).
    lambda_physics_schedule
        Optional explicit :class:`LambdaScheduler` for the physics loss.
        When ``None``, ``sensor_plus_physics`` uses
        ``FixedLambda(lambda_physics_value)`` — pass in a
        :class:`LinearRampLambda` to enable warmup.
    """
    if mode not in ABLATION_MODES:
        raise ValueError(
            f"unknown ablation mode {mode!r}; valid modes: {ABLATION_MODES}"
        )

    torch.manual_seed(seed)

    network, sensor_indices = _build_fixture(fixture)
    sensor_mask = sensor_mask_from_indices(network.num_nodes, sensor_indices)
    features = build_graph_features(network, sensor_mask=sensor_mask)

    dataset = _build_dataset(
        network,
        data=data,
        num_steps=num_steps,
        seed=seed,
        window=window,
    )

    model = DPHMPINN(
        node_in_dim=features.node_feature_dim,
        edge_in_dim=features.edge_feature_dim,
        seq_in_dim=dataset.node_feature_dim,
        hidden_dim=hidden_dim,
        force_fallback=True,
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    lam_data, lam_phys = _lambdas_for_mode(
        mode,
        lambda_data_value,
        lambda_physics_value,
        lambda_data_schedule,
        lambda_physics_schedule,
    )
    config = TrainConfig(
        num_iterations=num_iterations,
        lambda_data=lam_data,
        lambda_physics=lam_phys,
        batch_size=batch_size,
    )

    t0 = time.perf_counter()
    metrics = train_loop(
        model=model,
        dataset=dataset,
        features=features,
        network=network,
        optimizer=optimizer,
        config=config,
    )
    elapsed = time.perf_counter() - t0
    metrics.elapsed_seconds = float(elapsed)
    metrics.batch_size = int(batch_size)

    return {
        "mode": mode,
        "fixture": fixture,
        "data": data,
        "batch_size": batch_size,
        "summary": metrics.summary(),
        "history": metrics.history,
    }


__all__ = ["ABLATION_MODES", "DATA_KINDS", "FIXTURES", "run_ablation"]
