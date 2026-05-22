# Units and Sign Conventions

A single, documented unit and sign convention runs through every layer
of the AquaOptima dPHM-PINN code base. Adapters are responsible for
converting their native source units into this canonical convention
before producing a `TelemetrySeries`. The physics core, model, loss
functions, and training loop all assume the convention below; deviating
from it without an explicit conversion produces silently-wrong outputs
that the physics residual will *not* catch.

## SI units used internally

| Quantity                | Unit                      | Symbol  |
|-------------------------|---------------------------|---------|
| Length, diameter        | metres                    | m       |
| Pipe roughness factor   | dimensionless (HW C-factor) | C     |
| Pressure / head         | metres of water column    | m       |
| Volumetric flow rate    | cubic metres per second   | m³/s    |
| Pump speed              | dimensionless ratio (0–1) | s       |
| Pump head gain          | metres of water column    | m       |
| Time                    | seconds                   | s       |
| Power                   | watts                     | W       |

The pressure-to-head identity is exact internally: the model's
`PressureHead` outputs are fed directly into `assemble_residuals` as
hydraulic heads. Real-world `bar` → `mWC` (and elevation offsets for
piezometric vs. gauge pressure) must be applied by the source adapter,
not by the physics core.

## Sign conventions

- **Edge orientation.** `edge_index` is `[2, E]` with row 0 = source
  node, row 1 = target node (PyG convention). A *positive* flow on an
  edge means water moves from source to target.
- **Demands.** `demands[n] > 0` means node `n` is a consumer (water
  leaves the network there). `demands[n] < 0` means node `n` is a
  supplier (water enters the network there). The mass-balance residual
  is `A @ flows - demands` on free nodes.
- **Pump head.** `pump_head_gain` returns a positive value when the
  pump is doing work on the fluid. In the energy residual the gain
  appears on the *target* node side: `h_d - h_u - gain = 0`.
- **Pipe head loss.** `hazen_williams_head_loss(q, ...)` is *signed*:
  positive flow ⇒ positive loss; negative flow ⇒ negative loss. The
  pipe energy residual is `h_u - h_d - loss = 0`.

## Fixed-head nodes (reservoirs / boundary)

`Network.fixed_head_mask` flags nodes whose heads are pinned to
`fixed_head_values`. The Newton solver:

- Removes their mass-balance equations from the residual.
- Substitutes their fixed values into the energy residual for every
  edge incident on them.

The synthetic generator overwrites those nodes' pressure tensor entries
with the fixed value at every time step so any sample drawn from a
`TelemetrySeries` is internally consistent with the network's boundary
conditions.

## Common pitfalls

- **bar ↔ mWC.** 1 bar ≈ 10.1972 m of water column. Off-by-this-factor
  errors look like pressure being "10× off" on import.
- **L/s vs. m³/s.** 1 m³/s = 1000 L/s. Mis-scaling here makes the
  physics residual blow up in a way that *looks* like the model is
  diverging.
- **Edge direction.** Reversing an edge silently negates every flow on
  it; if a sign error survives validation it produces inconsistent
  mass balance.
- **Pressure vs. head.** Gauge pressure does not include elevation;
  hydraulic head does. The model treats its `pressure` output as
  hydraulic head — adapter-side conversion is mandatory for any real
  EPANET ingestion.
