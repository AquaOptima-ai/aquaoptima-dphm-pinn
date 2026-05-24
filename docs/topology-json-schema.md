# JSON Topology Schema for dPHM Networks

The JSON loader at `aquaoptima.dphm.load_network_from_json` accepts an
EPANET-style topology description — either an in-memory `dict` or a
path to a `.json` file — and returns the same
`aquaoptima.dphm.Network` dataclass the rest of the stack consumes.
It is **source-agnostic**: it carries only structural hydraulic
topology, never PLC / PAC / SCADA tag bindings, site metadata, or
field-adapter configuration.

If you need to map telemetry channels onto a SCADA / PLC / historian
data source, that responsibility stays in
`aquaoptima.dataio.tag_map.SiteTagMap` — see `docs/safety-boundary.md`
and `docs/telemetry-abstraction.md` for the boundary diagram.

## Canonical form

```json
{
  "nodes": [
    {"id": "n0", "demand": -0.05, "fixed_head": true,
     "head_value": 100.0, "elevation": 0.0},
    {"id": "n1", "demand":  0.02, "fixed_head": false},
    {"id": "n2", "demand":  0.03, "fixed_head": false}
  ],
  "edges": [
    {"id": "p0", "source": "n0", "target": "n1", "kind": "pipe",
     "length": 200.0, "diameter": 0.20, "c_factor": 130.0},
    {"id": "p1", "source": "n1", "target": "n2", "kind": "pipe",
     "length": 180.0, "diameter": 0.18, "c_factor": 130.0}
  ]
}
```

## Field reference

### Nodes

| Field        | Type   | Required                         | Meaning |
|--------------|--------|----------------------------------|---------|
| `id`         | string | yes                              | Stable unique node identifier |
| `demand`     | float  | no (default 0.0)                 | Positive = consumption (m^3/s), negative = supply |
| `fixed_head` | bool   | no (default false)               | Reservoir / tank / pressurised boundary |
| `head_value` | float  | yes iff `fixed_head=true`        | Pinned hydraulic head in metres |
| `elevation`  | float  | no (default 0.0)                 | Informational; reserved for a future elevation-aware energy residual |

### Edges

| Field         | Type        | Required                   | Meaning |
|---------------|-------------|----------------------------|---------|
| `id`          | string      | yes                        | Stable unique edge identifier |
| `source`      | string      | yes                        | Upstream node id |
| `target`      | string      | yes                        | Downstream node id |
| `kind`        | string      | yes (`"pipe"` or `"pump"`) | Edge classification |
| `length`      | float       | yes for pipes (>0)         | Pipe length in metres |
| `diameter`    | float       | yes for pipes (>0)         | Internal diameter in metres |
| `c_factor`    | float       | yes for pipes (>0)         | Hazen-Williams roughness coefficient |
| `pump_coeffs` | [a0,a1,a2]  | yes for pumps (`a0 > 0`)   | Pump curve `H(Q, s) = a0 s^2 + a1 s Q + a2 Q^2` |
| `pump_speed`  | float       | no for pumps (default 1.0) | Affinity-law speed multiplier |

## Validation surface

`load_network_from_json` raises `ValueError` with a descriptive
message for every one of these cases (each has a dedicated test in
`tests/dphm/test_network_io.py`):

* missing `nodes` / `edges` keys, or empty `edges`;
* missing `id` on nodes, missing `source` / `target` on edges;
* duplicate node ids; duplicate edge ids;
* edges referencing unknown source / target node ids;
* fixed-head nodes missing `head_value`;
* topologies with zero fixed-head nodes (singular hydraulic system);
* unknown edge `kind` (must be `"pipe"` or `"pump"`);
* non-positive `length`, `diameter`, or `c_factor` on a pipe edge;
* pump edges missing or malformed `pump_coeffs`, or with non-positive
  shut-off head `a0`.

The returned `Network` re-runs all `Network.__post_init__` checks, so
any residual shape / dimension issue surfaces there.

## Example

A worked example lives at `docs/examples/topology_3node_branch.json`.
It describes a tiny three-node branch with one reservoir, two demand
nodes, and two pipes — small enough to read at a glance, large enough
to exercise every required pipe-edge field. Round-trip test:
`tests/dphm/test_topology_example.py`.

```python
from pathlib import Path
from aquaoptima.dphm import load_network_from_json

doc = Path("docs/examples/topology_3node_branch.json")
network = load_network_from_json(doc)
assert network.num_nodes == 3
assert network.num_edges == 2
```

## What this loader is not

* **Not a PLC / PAC / SCADA adapter.** It does not open a Modbus
  socket, subscribe to OPC-UA tags, parse a Wonderware historian
  export, or read any field bus. Telemetry tag bindings stay in
  `aquaoptima.dataio.tag_map`.
* **Not an EPANET runtime.** The schema is EPANET-style but the
  loader does not invoke EPANET; it just parses topology into the
  existing `Network` dataclass and lets the dPHM core solve.
* **Not a write/control path.** All loaded topologies are read-only
  inputs to the differentiable forward model.

See `docs/sprint-roadmap.md` for the deferred items (real EPANET /
WNTR import, sparse / Krylov solver, sensor placement) the team will
sequence after Sprint 10.
