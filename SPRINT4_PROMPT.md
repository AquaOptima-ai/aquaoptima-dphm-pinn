# Sprint 4 — Replay ingestion and existing-control compatibility demo

Continue from completed Sprints 2-3. Preserve existing APIs and tests.

## Goal
Provide a runnable local demo that replays station snapshots through config -> ingestion -> normalization -> quality -> MVP wrapper -> authority gate -> audit/API.

## Correct PLC/PAC framing
This demo must not touch live PLC/PAC. It proves the new architecture can preserve baseline control compatibility using replay fixtures. Existing commissioned MVP write behavior is represented by `baseline_mvp` + authority decision, not a live write.

## Create/modify
```
aquaoptima_lite/ingestion/__init__.py
aquaoptima_lite/ingestion/base.py
aquaoptima_lite/ingestion/replay.py
aquaoptima_lite/normalization/__init__.py
aquaoptima_lite/normalization/tag_mapper.py
aquaoptima_lite/normalization/units.py
aquaoptima_lite/normalization/snapshot_builder.py
aquaoptima_lite/app/demo.py
scripts/run_optimizer_lite_demo.py
tests/fixtures/replay/legacy_station_replay.jsonl
tests/replay/test_replay_runtime_cycle.py
```

## Requirements
- Replay adapter reads JSONL where each line is a raw tag dict or canonical-ish snapshot dict.
- Tag mapper maps legacy/MVP names into canonical fields. Support at least keys from the fixtures: timestamp, system_mode/manual/auto, measured_head, measured_flow, pumpa_on/freq/flow/efficiency, pumpb..., pump trip/alarm if present.
- Unit normalizer supports passthrough for bar/head, m3h flow, Hz frequency; keep extensible but simple.
- Snapshot builder creates `StationSnapshot` from mapped tags and config.
- Demo script arguments: `--config`, `--replay`, `--cycles`, optional `--audit-db`.
- Demo prints quality status, recommendation source, authority gate decision, audit DB path.
- At least 4 replay cycles: pass, manual block, trip block, missing-flow warning.
- Audit row count equals cycle count.

## Verification before finish
Run:
```
python -m compileall -q aquaoptima_lite tests scripts
python -m pytest tests/unit tests/contract tests/replay -q
python scripts/run_optimizer_lite_demo.py --config config/examples/legacy_station_001.yaml --replay tests/fixtures/replay/legacy_station_replay.jsonl --cycles 4
git diff --check
```
Leave files unstaged. Do not commit. Report summary and tests.
