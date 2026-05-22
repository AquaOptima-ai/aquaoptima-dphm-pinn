# Telemetry Abstraction

SCADA is one of several possible telemetry sources, not a synonym for
"data input". Sprint 4.5 generalises the data path so every source
adapter eventually produces the same canonical container
(`TelemetrySeries`) described by the same metadata
(`SiteTagMap` + `TagDefinition`).

## Why generalise the term

Real AquaOptima deployments will read from at least the following
upstream systems:

| Source            | Reality on most sites                                |
|-------------------|------------------------------------------------------|
| **PLC**           | Siemens S7 / Allen-Bradley over Modbus or PROFINET.  |
| **PAC**           | Programmable automation controllers (PLC + PC mix).  |
| **SCADA**         | Wonderware, Ignition, ClearSCADA frontends.          |
| **Historian**     | OSIsoft PI, AVEVA Historian, Canary REST APIs.       |
| **MQTT**          | Sparkplug-B brokers; common in greenfield deploys.   |
| **CSV / Parquet** | Operator exports, audits, offline backfills.         |
| **Synthetic**     | The Sprint 1–4 default; physics-consistent in Sprint 5. |

Calling all of these "SCADA" hides where the bytes actually came from
and conflates the *format* (a stream of named floats and bools) with
the *origin* (a particular control or data system). The Sprint 4.5
rename keeps SCADA as an honest example of one source, not the name of
the abstraction.

## Canonical types (Sprint 4.5)

- `TelemetrySeries` — pressure / flow / demand tensors plus optional
  per-channel quality tensors. Drop-in interface for `WindowDataset`.
- `SiteTagMap` — per-site tag declaration (which tags exist, what kind,
  which node/edge/pump they tie to, sampling interval, source type).
- `TagDefinition` — a single tag with `name`, `kind`, `source_address`,
  `unit`, optional `node_id`/`edge_id`/`pump_id`, and a `writable`
  flag (defaults to `False`).
- `SourceType` — `SYNTHETIC | CSV | PLC | PAC | SCADA | HISTORIAN | MQTT`.
- `TagKind` — `PRESSURE | FLOW | PUMP_SPEED | PUMP_STATUS | POWER |
  COMMAND | ALARM`.
- `QualityFlag` — `GOOD | MISSING | STALE | FLATLINE | OUTLIER |
  BAD_QUALITY | MANUAL_OVERRIDE` with an `is_usable` helper.

## Adapter strategy

Each future adapter is a *function-shaped* component: poll the source,
convert units, produce a `TelemetrySeries` (or a stream of frames)
that matches a `SiteTagMap`. AquaOptima core does *not* embed adapter
SDKs — instead, each adapter lives in its own optional dependency
extra (e.g. `aquaoptima[plc]`, `aquaoptima[opcua]`) so a deployment
only installs what it needs.

```
Source (PLC / PAC / SCADA / Historian / MQTT / CSV)
   │
   ▼
Adapter   ── implements ──▶ SiteTagMap
   │
   ▼  poll / subscribe / read
Raw values
   │
   ▼  unit + sign conversion
TelemetrySeries
   │
   ▼
WindowDataset → DPHMPINN → composite_loss → training loop
```

## Backward compatibility

The Sprint 1–4 names continue to import cleanly:

```python
from aquaoptima.dataio import ScadaSeries, generate_synthetic_scada
```

These are aliases of `TelemetrySeries` / `generate_synthetic_telemetry`
respectively. New code should prefer the canonical names; legacy code
keeps working unchanged.

## What is *not* in Sprint 4.5

- No real adapter implementations (Modbus / OPC-UA / MQTT / REST / CSV).
- No live write path back to a controller.
- No physics-consistent synthetic generator — still the Sprint 3
  hand-tuned sinusoid.
- No quality-flag gating in `composite_loss`.

These are explicit Sprint 5+ items. The Sprint 4.5 deliverable is *only*
the data model and rename so the next sprint can land adapters and
physics-consistent training behind a stable interface.
