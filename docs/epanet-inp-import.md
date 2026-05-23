# EPANET `.inp` Topology Import (Sprint 11)

Sprint 11 extends the dPHM topology loader stack with optional
EPANET-style `.inp` import, alongside the Sprint 8 JSON loader. The
public entry point is one function:

```python
from aquaoptima.dphm import load_network_from_inp

network = load_network_from_inp(
    "docs/examples/epanet_reference_loop.inp",
    parser="auto",        # "auto" | "fallback" | "wntr"
    units="si",           # only "si" supported in Sprint 11
    default_c_factor=130, # used when a pipe row omits roughness
)
```

`load_network_from_inp` returns the same `aquaoptima.dphm.Network`
dataclass every other loader and fixture produces — so any code that
already consumes a `Network` from the JSON loader, the hand-built
fixtures, or `make_grid_network` works with an INP-loaded network
unchanged.

This is **topology import only**. The loader does not:

- start or talk to an EPANET binary / runtime;
- run a hydraulic simulation;
- bind PLC / PAC / SCADA tags (that responsibility stays in
  `aquaoptima.dataio.tag_map`);
- provide any write or control path.

See `docs/safety-boundary.md` for the full safety / boundary diagram.

## Back-ends

| `parser`     | Behaviour                                                                                                         |
|--------------|-------------------------------------------------------------------------------------------------------------------|
| `"auto"`     | Prefer the WNTR back-end if `wntr` is importable, otherwise use the built-in fallback parser. **Default.**        |
| `"fallback"` | Always use the built-in fallback parser. Dependency-free.                                                          |
| `"wntr"`     | Use the upstream [WNTR](https://github.com/USEPA/WNTR) loader. Raises `ImportError` if `wntr` is not installed.    |

WNTR is an **optional** dependency. The base test suite and base
install never require it. To opt in:

```bash
pip install 'aquaoptima-dphm-pinn[epanet]'    # pulls in wntr>=1.0
# or
pip install wntr
```

When WNTR is not installed, the optional test module
`tests/dphm/test_wntr_optional_import.py` skips cleanly via
`pytest.importorskip("wntr")`.

## Fallback parser — supported INP subset

The fallback parser is intentionally small. It supports the subset
needed to load steady-state reference fixtures.

### Honoured sections

| Section          | Notes                                                                                                    |
|------------------|----------------------------------------------------------------------------------------------------------|
| `[JUNCTIONS]`    | id, elevation, baseline demand. Pattern column is ignored (steady-state).                                |
| `[RESERVOIRS]`   | id, head. Pattern column is ignored.                                                                     |
| `[TANKS]`        | id, elevation, init-level → mapped to a fixed-head boundary at `elev + init_level`. Curves ignored.       |
| `[PIPES]`        | id, node1, node2, length, diameter, roughness, optional minor-loss (ignored), optional status (`OPEN`).  |
| `[OPTIONS]`      | `Units` (flow-unit family) and `Headloss` (must be `H-W`).                                               |
| `[TITLE]`, `[COORDINATES]`, `[PATTERNS]`, `[REPORT]`, `[TIMES]`, `[END]`, ... | Silently ignored.                                  |

### Sections that fail loudly

| Section          | Reason                                                                                                                                |
|------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| `[PUMPS]`        | Raises `ValueError`. The fallback parser does not yet translate EPANET pump curves into the dPHM pump-affinity representation.        |
| `[VALVES]`       | Raises `ValueError`. The dPHM steady-state core does not model valves.                                                                |

For pump fixtures, prefer the JSON loader
(`load_network_from_json`, see `docs/topology-json-schema.md`) or
install WNTR. The WNTR back-end currently also refuses INP files that
declare pumps or valves — same scope boundary, different error site.

## Unit conventions

EPANET picks per-flow-unit conventions for length and diameter:

- **SI flow units** (`LPS`, `LPM`, `CMH`, `CMS`, `MLD`):
  length in metres, diameter in **millimetres**, head/elevation in
  metres. Supported.
- **US-customary flow units** (`CFS`, `GPM`, `MGD`, `IMGD`, `AFD`):
  length in feet, diameter in inches, head in feet. **Not
  supported.** US-style files raise a clear `ValueError`. Convert
  upstream, or use WNTR which performs its own conversion to SI
  before our adapter reads its `WaterNetworkModel`.

Demand conversions (file → m³/s) implemented in the fallback parser:

| `Units` directive | factor                |
|-------------------|-----------------------|
| `LPS`             | `× 1e-3`              |
| `LPM`             | `× 1 / 60_000`        |
| `CMH`             | `× 1 / 3600`          |
| `CMS`             | `× 1` (no conversion) |
| `MLD`             | `× 1000 / 86_400`     |

If `[OPTIONS]` is absent or omits `Units`, the parser assumes the
EPANET default of `LPS`. If `Headloss` is not `H-W`, the parser
raises — the dPHM core is Hazen-Williams.

## Mass balancing

EPANET INP files often declare junction demands without a matching
explicit supply row; the reservoir(s) implicitly supply the deficit.
Our `Network` dataclass expects `sum(demands) ≈ 0` for downstream
clarity, so the fallback parser **absorbs the demand sum onto the
fixed-head node(s)** at load time. Fixed-head nodes drop out of the
mass-balance residual term anyway — this is purely cosmetic, but it
keeps loaded networks comparable with the JSON loader and the
hand-built fixtures.

## Shipped fixture

`docs/examples/epanet_reference_loop.inp` is a tiny 5-node looped
distribution sample (1 reservoir + 4 junctions, 5 pipes) in SI
(`LPS`) flow units. It is small enough to read at a glance and large
enough to exercise pipe loops, reservoir boundaries, and mm→m
diameter conversion.

Round-trip:

```python
from pathlib import Path
from aquaoptima.dphm import load_network_from_inp, newton_solve

net = load_network_from_inp(
    Path("docs/examples/epanet_reference_loop.inp"),
    parser="fallback",
)
result = newton_solve(net, max_iterations=200, tol=1e-9, jacobian_mode="analytic")
assert result.converged
```

Tests:

- `tests/dphm/test_inp_network_io.py` — fallback parser, full error
  surface, solver compatibility, batched residual compatibility.
- `tests/dphm/test_wntr_optional_import.py` — optional WNTR
  comparison, skipped when WNTR is not installed.
- `tests/dataio/test_inp_physics_telemetry.py` — physics-consistent
  telemetry round-trip on the INP-loaded network.

## What this loader is **not**

- Not an EPANET runtime — no hydraulic simulation, no extended-period
  integration, no quality / age modelling.
- Not a SCADA / PLC / PAC adapter — no Modbus, OPC-UA, MQTT, or
  historian binding.
- Not a write or control path — all loaded topologies are read-only
  inputs to the differentiable forward model.
- Not field-validated — Sprint 11 only proves that the topology
  *parses and solves*; on-site accuracy claims remain out of scope.

## Roadmap

Deferred to a future sprint:

- US-customary flow units (`GPM`, `CFS`, …) on the fallback parser.
- Pump curve translation (LINEAR / HEAD / POWER → dPHM pump
  affinity).
- Larger reference fixtures (e.g. the EPANET `Net1` / `Net3` shipped
  examples) routed through the WNTR back-end.

See `docs/sprint-roadmap.md` for the current ordering.
