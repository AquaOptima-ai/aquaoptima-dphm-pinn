# Sprint 2 — Optimizer Lite Runtime Contracts, Config, Snapshots, and Authority Gate

You are implementing Sprint 2 of AquaOptima Pump Station Optimizer Lite.

## Context

This quick-win product is for a single legacy pump station currently running MVP v1 (`/home/hunter_lin/work/repos/water-pump-opt`). Do not modify that legacy repo. Implement new product package code in this repo/worktree.

Correct PLC/PAC framing:
- Do NOT remove PLC/PAC control from the product.
- Existing MVP baseline PLC/PAC control path may remain active where commissioned.
- This sprint does not implement live PLC/PAC writes or network clients.
- The goal is to make control authority explicit, configurable, audited, and gated.
- No learner/AI/Operations Console component may bypass PLC/PAC interlocks, manual mode, trips, or authority gate.

Out of scope:
- PINN
- full WDN dPHM
- full hydraulic solver
- full PID replacement
- direct live PLC/Modbus/MQTT/ThingsBoard clients
- learned optimizer control writes

## Goal

Create the Optimizer Lite package foundation and control-authority vocabulary without changing any live control behavior.

## Required files to create

```text
aquaoptima_lite/
  __init__.py
  config/
    __init__.py
    models.py
    loader.py
  runtime/
    __init__.py
    models.py
    modes.py
    reason_codes.py
    quality.py
    authority_gate.py

tests/unit/
  test_config_loader.py
  test_station_snapshot.py
  test_quality.py
  test_authority_gate.py

config/examples/legacy_station_001.yaml

tests/fixtures/snapshots/
  snapshot_pass.json
  snapshot_manual_mode_block.json
  snapshot_trip_block.json
  snapshot_missing_flow_warn.json
```

## Implementation details

Use Python stdlib dataclasses/enums where possible. If PyYAML is unavailable, implement a minimal safe fallback or use JSON-compatible YAML subset parsing; but PyYAML is likely available. Do not introduce heavy dependencies.

### Runtime modes

Create enum/string constants for:
- `monitor_only`
- `baseline_control`
- `baseline_plus_learning_shadow`
- `learned_advisory`
- `learned_supervisory_control` (future mode, gated off unless enabled)

Semantics:
- `baseline_control`: existing MVP-style PLC/PAC output remains allowed if configured and commissioned.
- `baseline_plus_learning_shadow`: baseline control can remain active; learner is observe-only.
- `learned_advisory`: learner can produce advisory evidence, no direct writes.
- `learned_supervisory_control`: future; must be blocked unless future_control_enabled is true.

### Config model

Represent at least:
- site id/name/timezone
- runtime default_mode, cycle_seconds, stale_after_seconds
- safety flags: require_auto_mode, block_on_any_trip, block_on_any_alarm, baseline_control_enabled, future_control_enabled, min/max frequency, max step, min/max pressure/flow, min_model_confidence_for_advisory
- data requirements: required/strongly_preferred/optional list
- pumps: id, display_name, role, min/max frequency, rated_power_kw optional
- tags: canonical tag id -> source/address/unit/scale/valid_min/valid_max/stale_after_seconds/required

Loader must:
- load YAML config file
- validate required sections
- return typed `SiteConfig`
- produce deterministic config hash (sha256 of canonical JSON representation)

### Runtime models

Create dataclasses:
- `PumpState`: pump_id, running, available, frequency_hz, trip_active, alarm_active, flow_m3h optional, power_kw optional, current_a optional
- `StationSnapshot`: timestamp, site_id, mode, pumps tuple/list, discharge_pressure_bar optional, head_m optional, flow_m3h optional, manual_mode bool, auto_mode bool, quality_flags tuple/list, config_hash
- `QualityDecision`: status `pass|warn|block`, reason_codes list, blocked_for_advisory, blocked_for_learning, blocked_for_future_control, confidence_penalty
- `CommandProposal` or `ControlIntent`: source (`baseline_mvp`, `learner`, `console`, `none`), target pump/frequency data optional, confidence optional
- `AuthorityGateDecision`: decision `allow|block|observe_only`, reason_codes list, source, write_allowed bool

### Reason codes

Include reason codes for at least:
- `manual_mode_active`
- `auto_mode_required`
- `pump_trip_active`
- `pump_alarm_active`
- `missing_required_tag`
- `missing_pressure_or_head`
- `missing_pump_frequency`
- `stale_required_tag`
- `flow_missing_learning_limited`
- `power_missing_savings_unverified`
- `source_not_allowed_in_mode`
- `future_control_disabled`
- `frequency_out_of_bounds`
- `baseline_control_disabled`

### Quality engine

Implement function like:

```python
def evaluate_quality(snapshot: StationSnapshot, config: SiteConfig) -> QualityDecision: ...
```

Expected behavior:
- manual mode -> block advisory/future control, reason `manual_mode_active`
- require_auto_mode and not auto -> block, reason `auto_mode_required`
- any trip -> block, reason `pump_trip_active`
- missing pressure/head -> block
- missing flow -> warn and block learning strong sample, not necessarily baseline control
- missing power/current -> warn for savings claim, not block baseline/advisory

### Authority gate

Implement function/class:

```python
def evaluate_authority(snapshot, quality, proposal, config) -> AuthorityGateDecision: ...
```

Expected behavior:
- If quality blocks advisory/future control, learner/console sources are blocked.
- `baseline_mvp` is allowed only in `baseline_control` or `baseline_plus_learning_shadow` when `baseline_control_enabled=true` and no manual/trip block.
- learner source is observe_only in `baseline_plus_learning_shadow`.
- learner source is observe_only or block in `learned_advisory` unless there is no write requested.
- `learned_supervisory_control` is blocked if `future_control_enabled=false`.
- Frequency outside configured bounds blocks.

## Fixtures

Create JSON fixtures for:
- pass: auto mode, no trips, required data present
- manual mode block
- trip block
- missing flow warning

## Tests

Write unit tests verifying:
- config loader loads `legacy_station_001.yaml` and config hash is stable
- snapshot fixture parses into StationSnapshot
- quality pass/warn/block cases
- authority gate allows baseline in `baseline_control` when safe
- authority gate observes learner in `baseline_plus_learning_shadow`
- manual/trip block baseline and learner
- future learned supervisory control blocked when `future_control_enabled=false`

## Verification commands to run before finishing

```bash
python -m compileall -q aquaoptima_lite tests
python -m pytest tests/unit -q
git diff --check
```

## Finish

After implementing, leave files unstaged. Do not commit. Report summary and test results.
