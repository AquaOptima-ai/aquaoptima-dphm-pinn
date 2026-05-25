# AMAX-5580 Read-only PLC/SCADA Integration Contract (Sprint 48)

Sprint 48 defines how an AMAX Edge instance can **read** telemetry from
site PLC / SCADA / CODESYS-facing systems without controlling anything.
It is a contract / specification sprint. It ships read-only integration
*contracts*, not a live OPC UA / Modbus / CODESYS / SCADA / PLC / MQTT /
HTTP / database / message-broker client.

This document is the audit-only companion to
`src/aquaoptima_contracts/edge/read_only_integration.py` and the
canonical helper `default_amax_read_only_integration_contract()`.

## What this sprint ships

- **Sprint 48 ships read-only integration contracts, not live adapters.**
- A canonical protocol vocabulary
  (`opc_ua`, `modbus_tcp`, `modbus_rtu`, `codesys_symbol`,
  `codesys_shared_memory`, `mqtt_sparkplug_read_only`) for the SDK to
  validate against.
- Frozen, audit-only SDK dataclasses:
  - `ReadOnlyTelemetrySource` — labels-only description of a read-only
    source (source id, canonical protocol, endpoint label, security
    zone label, polling interval, freshness threshold, credential
    reference label, access mode, notes).
  - `ReadOnlyTagBinding` — links a source-path label to a Sprint 42
    `TelemetryTagSpec` (axis / role / unit / target id), with explicit
    quality / freshness behavior tokens.
  - `TelemetryFreshnessPolicy` — max age, stale behavior, missing
    behavior, source-quality-flag to SDK-quality-flag mapping, and
    replay-equivalence expectations.
  - `ReadOnlyIntegrationContract` — full audit bundle combining the
    sources, tag bindings, freshness policy, compatibility notes, and
    safety notes.
  - `ReadOnlyIntegrationDiagnostics` — deterministic warnings / errors
    surfaced by `diagnose_read_only_integration_contract()` for
    duplicate binding ids, unsupported protocols, dangling binding
    source references, missing freshness coverage, and unsafe
    vocabulary in labels.
  - `ReplayToLiveEquivalenceEvidence` — captures how a replay /
    surrogate dataset maps to a live read-only source. Defaults to
    `not_evaluated` until a real source verification is signed off.

## OPC UA / Modbus / CODESYS entries are source-shape contracts only

The canonical default contract enumerates six source records and four
tag bindings spanning OPC UA subscription, Modbus TCP polling, Modbus
RTU serial polling, CODESYS symbol subscription, CODESYS shared-memory
mapping, and an IT-zone MQTT Sparkplug read-only NDATA / DDATA
subscription. **Every entry is a source-shape contract only.** The
contract carries no live client, no socket, no asyncua, no opcua, no
pymodbus, no paho-mqtt, no requests, no httpx, no sqlite3, no
psycopg2, no pymongo, no redis, and no kafka dependency. The SDK
module is stdlib-only.

## Network segmentation, credential handling, and labels

- All endpoints, tag paths, registers, symbols, and security zones
  are captured as **labels / references**, not live connection
  strings.
- Credential handling uses `credential_reference_label` — a label
  that points to whichever secret-management system the site uses. An
  explicit empty string means "no credential handling is required for
  this read-only source". The SDK contract carries **no secrets, no
  passwords, no tokens, and no API keys.**
- Network segmentation labels (`ot_zone`, `it_zone`) describe which
  zone the read-only source lives in. They do not authorise any
  cross-zone traffic, write, dispatch, actuation, setpoint, or
  control surface; they are audit metadata only.

## Telemetry freshness, staleness, and replay-to-live equivalence

`TelemetryFreshnessPolicy` is **audit evidence, not a live timer**. It
captures the maximum acceptable age of a sample, the canonical
behavior when a sample exceeds that age (`flag_stale` / `drop_frame` /
`hold_last_good`), the canonical behavior when a sample is missing
(`flag_missing` / `drop_frame` / `hold_last_good`), the mapping from
source-side quality flags to the SDK quality vocabulary, and the
replay-equivalence expectations a future auditor must verify.

`ReplayToLiveEquivalenceEvidence` is the **audit record** that connects
a Sprint 42 `ShadowReplayDataset` to a Sprint 48
`ReadOnlyTelemetrySource`. The default record's `equivalence_status`
is `not_evaluated` — replay datasets are surrogate evidence until a
real source verification has happened. There is no live connection
opened by this record.

## Non-negotiable safety boundary

Sprint 48 reaffirms — in source docstrings, canonical record notes,
and tests — the boundary that Sprint 45+ AMAX work must never cross:

- no live OT binding
- no PLC/PAC/SCADA write
- no command emission
- no setpoint output
- no control-loop closure
- no direct VFD / pump / actuator control from AquaOptima Edge
- no bypass of site PLC interlocks, permissives, trips, manual mode,
  or emergency stop
- no Edge Runtime daemon / service implementation
- no AI / Optimization Server runtime, no Operations Console runtime
- no live OPC UA / Modbus / CODESYS / SCADA / PLC / MQTT / HTTP /
  database / message-broker client in this module
- no model artifact loading from disk, no inline model weights
- no credentials, passwords, tokens, API keys, or connection secrets
  in docs / tests / source

The site PLC / pump-station PLC retains direct VFD / pump / actuator
authority.

## Sprint 49 — next gate

After Sprint 48 passes, Sprint 49 should be **AMAX Site Deployment
Readiness / OT Certification Evidence Package**. Sprint 49 must not
introduce live OT binding, PLC/PAC/SCADA write, command emission,
setpoint output, control-loop closure, or any Edge Runtime daemon
implementation. The site PLC remains the direct VFD / pump / actuator
authority for every Sprint 45+ AMAX deliverable until a future safety
gate explicitly approves a supervised, bounded write surface.
