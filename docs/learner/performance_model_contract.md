# Optimizer Lite Shadow Performance Model Contract

Sprint 7 adds a lightweight learned pump/combination performance model for **shadow evidence only**.

## Purpose

The model summarizes accepted learner samples into auditable per-combo performance evidence:

- observed flow;
- observed head;
- observed power;
- specific energy;
- sample count;
- confidence/readiness;
- reason codes.

It is intentionally simple and deterministic: the first implementation uses local per-combo averages over accepted samples. This is enough to show whether the runtime can learn useful pump/combo evidence without pretending to be a qualified controller.

## Safety boundary

The model is not a controller.

```text
influences_control=False
no PLC/PAC/SCADA write path
no command output
no ControlIntent mutation
baseline remains control reference
```

Any future control use requires a separate safety-qualified release.

## Core objects

### PerformanceFeature

A normalized row derived from an accepted `LearnerSample`.

Required fields:

- `timestamp`
- `site_id`
- `combo_key`
- `observed_head_m`
- `total_flow_m3h`
- `total_power_kw`
- `avg_frequency_hz`
- `running_pump_count`
- `specific_energy_kwh_per_m3`

### PerformanceFeatureSet

Container returned by the feature builder.

Fields:

- `readiness`: `ready | insufficient_data | missing_required_tags | invalid_quality`
- `reason_codes`
- `features`
- `influences_control=False`

### PerformanceModelResult

Audit/API-ready model evidence.

Fields:

- `model_id`
- `model_version`
- `readiness`
- `combo_key`
- `training_sample_count`
- `confidence`
- `reason_codes`
- optional estimates:
  - `estimated_flow_m3h`
  - `estimated_head_m`
  - `estimated_power_kw`
  - `estimated_specific_energy_kwh_per_m3`
- `influences_control=False`

## Readiness states

| State | Meaning |
|---|---|
| `ready` | Enough accepted samples exist for the combo. |
| `insufficient_data` | No samples, too few samples, or unsupported combo. |
| `missing_required_tags` | Required sample fields are missing/non-positive. |
| `invalid_quality` | Reserved for future feature-builder quality failures. |

## Demo

```bash
python scripts/run_optimizer_lite_demo.py \
  --config config/examples/legacy_station_001.yaml \
  --replay tests/fixtures/replay/legacy_station_replay.jsonl \
  --cycles 4 \
  --learner-shadow \
  --learner-performance-shadow
```

Expected shape:

```text
performance_model readiness=insufficient_data confidence=0.5 training_sample_count=1 influences_control=False
```

The demo fixture has one clean accepted sample and three blocked/warn cycles, so the model reports insufficient data rather than making an unsafe claim.
