"""Canonical telemetry container and synthetic generator.

Sprint 4.5 generalises the data path so SCADA is treated as one possible
source of *telemetry* alongside PLC, PAC, historian, CSV, and MQTT
streams. All downstream code (``WindowDataset``, model training, loss
functions) consumes the same ``TelemetrySeries`` shape regardless of
origin.

The synthetic generator in this module is deliberately shape-correct
but not physics-consistent — Sprint 5 will replace its internals with
a ``newton_solve``-driven series that satisfies Hazen-Williams by
construction. The data contract (tensor shapes, dtype, seedability)
will stay the same so existing tests and the ``WindowDataset`` keep
working without changes.

Backward compatibility:

* ``ScadaSeries`` is an alias of :class:`TelemetrySeries`.
* ``generate_synthetic_scada`` is an alias of
  :func:`generate_synthetic_telemetry`.

Both alias paths are kept indefinitely so existing Sprint 1–4 imports
continue to resolve.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

import torch

from aquaoptima.dphm import Network, newton_solve


@dataclass
class TelemetrySeries:
    """A bundle of telemetry time series for one :class:`Network`.

    All fields share a common leading time axis ``T``. The trailing
    axes match the structure of the underlying :class:`Network`:

    Attributes
    ----------
    pressure
        Per-node pressure / head, shape ``[T, N]``. Units: metres of
        water (the dPHM internal head convention). For sources whose
        native unit is bar, convert before instantiation.
    flow
        Per-edge volumetric flow rate, shape ``[T, E]``. Units: m^3/s.
        Positive flow follows the directed edge orientation
        ``source -> target`` (see ``docs/units-and-sign-conventions.md``).
    demand
        Per-node demand, shape ``[T, N]``. Positive = consumption,
        negative = supply.
    quality
        Optional per-channel quality flag tensors keyed by channel name
        (e.g. ``"pressure"``, ``"flow"``, ``"demand"``). Each entry is
        a tensor sized to match its channel. ``None`` means "treat
        every sample as good" — the historical Sprint 1–4 behaviour.
        Quality semantics are defined by
        :class:`aquaoptima.dataio.quality.QualityFlag`.
    """

    pressure: torch.Tensor  # [T, N]
    flow: torch.Tensor      # [T, E]
    demand: torch.Tensor    # [T, N]
    quality: Optional[dict[str, torch.Tensor]] = field(default=None)

    @property
    def num_steps(self) -> int:
        """Number of time steps in the series (the ``T`` axis)."""
        return int(self.pressure.shape[0])

    @property
    def num_nodes(self) -> int:
        """Number of network nodes (the ``N`` axis of pressure/demand)."""
        return int(self.pressure.shape[1])

    @property
    def num_edges(self) -> int:
        """Number of network edges (the ``E`` axis of flow)."""
        return int(self.flow.shape[1])


def generate_synthetic_telemetry(
    network: Network,
    num_steps: int,
    seed: int,
    window: int = 32,
) -> TelemetrySeries:
    """Generate a deterministic ``num_steps``-long synthetic telemetry series.

    ``window`` is the minimum guaranteed lookback; the caller asks for at
    least ``window`` steps so a single training sample can be built by
    :class:`aquaoptima.dataio.window_dataset.WindowDataset`.

    The series is *shape-correct, leak-free, seedable* but **not**
    physics-consistent — see ``docs/telemetry-abstraction.md`` for the
    Sprint 5 plan that replaces the internals with a ``newton_solve``-
    driven generator while preserving this signature.
    """
    if num_steps <= 0:
        raise ValueError(f"num_steps must be positive, got {num_steps}")
    if num_steps < window:
        raise ValueError(
            f"num_steps={num_steps} too short for window={window}; "
            f"need at least window steps"
        )

    gen = torch.Generator(device="cpu").manual_seed(int(seed))

    N = network.num_nodes
    E = network.num_edges

    t = torch.arange(num_steps, dtype=torch.get_default_dtype()).unsqueeze(1)  # [T, 1]

    base_demand = network.demands.to(torch.get_default_dtype()).unsqueeze(0)  # [1, N]
    phase = torch.linspace(0.0, 1.0, N).unsqueeze(0)
    cycle = torch.sin(2 * torch.pi * (t / 24.0 + phase))
    noise_d = torch.randn(num_steps, N, generator=gen) * 0.01
    demand = base_demand + 0.2 * base_demand.abs() * cycle + noise_d * base_demand.abs()

    # Per-node "pressure" is a damped mirror of demand fluctuation around
    # a nominal head of 50 m. Fixed-head nodes are pinned to their value.
    nominal_head = 50.0
    pressure = nominal_head - 10.0 * cycle + torch.randn(
        num_steps, N, generator=gen
    ) * 0.05
    fixed = network.fixed_head_mask
    if fixed.any():
        fixed_vals = network.fixed_head_values.to(torch.get_default_dtype())
        pressure[:, fixed] = fixed_vals[fixed].unsqueeze(0).expand(num_steps, -1)

    # Per-edge flow: a nominal 0.05 m^3/s baseline modulated by the daily
    # cycle averaged over the two endpoint nodes.
    src = network.edge_index[0]
    dst = network.edge_index[1]
    edge_cycle = 0.5 * (cycle[:, src] + cycle[:, dst])
    flow = 0.05 + 0.02 * edge_cycle + torch.randn(
        num_steps, E, generator=gen
    ) * 0.002

    return TelemetrySeries(pressure=pressure, flow=flow, demand=demand)


def generate_physics_consistent_telemetry(
    network: Network,
    num_steps: int,
    seed: int = 0,
    window: int = 32,
    *,
    demand_amplitude: float = 0.2,
    demand_noise_std: float = 0.01,
    solver_max_iterations: int = 200,
    solver_tol: float = 1e-9,
    dtype: torch.dtype = torch.float64,
) -> TelemetrySeries:
    """Generate a physics-consistent ``num_steps``-long telemetry series.

    Unlike :func:`generate_synthetic_telemetry`, the output of this
    function satisfies the dPHM mass + energy residual to within
    ``solver_tol`` at every timestep. The series is built by:

    1. Constructing a deterministic per-step demand pattern (daily
       cosine modulation around the network's nominal demands plus a
       small seeded noise term).
    2. Re-balancing the demand vector so the network is mass-consistent
       (any supply node — i.e. nodes whose nominal demand is negative —
       absorbs the perturbation so ``sum(demands) == 0``).
    3. Calling :func:`aquaoptima.dphm.newton_solve` with the per-step
       demand vector to obtain physically consistent heads and flows.

    The signature mirrors :func:`generate_synthetic_telemetry` so the
    downstream :class:`WindowDataset` and training code consume the
    output without modification.

    Parameters
    ----------
    network
        Network fixture (branch / single_loop / pump). Any
        :class:`Network` is supported provided the Sprint 2 Newton
        solver converges on it.
    num_steps
        Number of time steps in the series. Must be ``>= window``.
    seed
        Seed for the demand noise generator. Deterministic for a fixed
        seed; differing seeds produce differing series.
    window
        Minimum lookback enforced by :class:`WindowDataset`. The
        generator does not use ``window`` directly except to keep the
        length-validation contract aligned with
        :func:`generate_synthetic_telemetry`.
    demand_amplitude
        Fractional amplitude of the daily cosine modulation applied to
        each node's nominal demand magnitude.
    demand_noise_std
        Standard deviation of the additive demand noise (in the same
        fractional sense as ``demand_amplitude``).
    solver_max_iterations, solver_tol
        Passed straight through to :func:`newton_solve`.
    dtype
        Working precision used inside the per-step solve. The returned
        tensors are cast to the default torch dtype so they slot into
        the existing dataset / model pipeline without a type mismatch.
    """
    if num_steps <= 0:
        raise ValueError(f"num_steps must be positive, got {num_steps}")
    if num_steps < window:
        raise ValueError(
            f"num_steps={num_steps} too short for window={window}; "
            f"need at least window steps"
        )

    gen = torch.Generator(device="cpu").manual_seed(int(seed))
    out_dtype = torch.get_default_dtype()

    N = network.num_nodes
    E = network.num_edges

    base_demand = network.demands.to(dtype)
    nominal_abs = base_demand.abs()
    phase = torch.linspace(0.0, 1.0, N, dtype=dtype)
    t_axis = torch.arange(num_steps, dtype=dtype).unsqueeze(1)  # [T, 1]
    cycle = torch.cos(
        2 * torch.pi * (t_axis / 24.0 + phase.unsqueeze(0))
    )  # [T, N]
    noise = torch.randn(num_steps, N, generator=gen, dtype=dtype) * demand_noise_std

    demand_t = (
        base_demand.unsqueeze(0)
        + demand_amplitude * nominal_abs.unsqueeze(0) * cycle
        + noise * nominal_abs.unsqueeze(0)
    )  # [T, N]

    # Cosmetic mass-balance: redistribute any drift onto the supply
    # node(s) so ``sum(demands_t) == sum(base_demand)``. This does not
    # affect residual computation (fixed-head nodes drop out of the
    # mass term) but it keeps the demand series interpretable and
    # ensures the perturbation does not migrate the network out of the
    # solver's basin of convergence.
    supply_mask = base_demand < 0
    if supply_mask.any():
        drift = demand_t.sum(dim=1) - base_demand.sum()  # [T]
        share = supply_mask.to(dtype) / supply_mask.sum().to(dtype)
        demand_t = demand_t - drift.unsqueeze(1) * share.unsqueeze(0)

    pressure_t = torch.zeros((num_steps, N), dtype=dtype)
    flow_t = torch.zeros((num_steps, E), dtype=dtype)

    for i in range(num_steps):
        net_i = replace(network, demands=demand_t[i].detach())
        result = newton_solve(
            net_i,
            max_iterations=solver_max_iterations,
            tol=solver_tol,
            dtype=dtype,
        )
        if not result.converged:
            raise RuntimeError(
                f"Newton solve did not converge at step {i}: "
                f"reason={result.reason}, residual_norm={result.residual_norm}"
            )
        pressure_t[i] = result.heads.to(dtype)
        flow_t[i] = result.flows.to(dtype)

    return TelemetrySeries(
        pressure=pressure_t.to(out_dtype),
        flow=flow_t.to(out_dtype),
        demand=demand_t.to(out_dtype),
    )


# --- Backward-compatible aliases -------------------------------------------
#
# Sprint 1-4 code imported ``ScadaSeries`` and ``generate_synthetic_scada``.
# These names remain available so old call sites keep working without
# modification. New code should prefer ``TelemetrySeries`` /
# ``generate_synthetic_telemetry``.

ScadaSeries = TelemetrySeries
generate_synthetic_scada = generate_synthetic_telemetry

__all__ = [
    "TelemetrySeries",
    "ScadaSeries",
    "generate_synthetic_telemetry",
    "generate_synthetic_scada",
    "generate_physics_consistent_telemetry",
]
