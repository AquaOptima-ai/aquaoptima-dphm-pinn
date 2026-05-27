# Optimizer Lite deployment readiness gate

Sprint 10 adds a deterministic pre-pilot readiness report for AquaOptima Pump Station Optimizer Lite.

## Command

```bash
python scripts/check_optimizer_lite_readiness.py \
  --config config/examples/legacy_station_001.yaml \
  --replay tests/fixtures/replay/legacy_station_replay.jsonl \
  --cycles 4
```

The command prints JSON to stdout. It is intended for pilot handoff evidence and CI/readiness checks.

## Status values

- `ready_for_pilot_review`: config, replay/demo, API evidence endpoint, and handoff checklist are present.
- `blocked`: one or more required gates failed, with machine-readable reason codes.

## Gate categories

- `config_exists`: site config can be loaded and hashed.
- `replay_exists`: replay/site-data fixture is present.
- `console_evidence_api`: `/console/evidence/current` is present.
- `demo_replay_cycles`: demo runtime produced the requested audit count.

## Safety boundary

The readiness report is a gate/report only.

- No learner/AI/Console direct write path.
- No uncontrolled or newly introduced PLC/PAC/SCADA write path.
- Existing MVP baseline control remains the authority/fallback.
- Readiness output is evidence, not commands.
- Readiness output does not mutate `ControlIntent`.
- Readiness output always reports `read_only=true` and `influences_control=false`.

## Operator handoff checklist

The report includes a minimum operator handoff checklist:

1. review Console evidence before pilot;
2. confirm site tag map and units;
3. confirm existing MVP baseline authority;
4. confirm no new field write path;
5. archive readiness report with operator handoff evidence.

This keeps Sprint 10 as packaging/deployment readiness for a quick-win pilot, not live OT integration or control expansion.
