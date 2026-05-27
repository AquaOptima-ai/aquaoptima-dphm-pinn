# Sprint 8 advisory ranking contract

Sprint 8 adds advisory-only learned pump/combo ranking and baseline comparison evidence for AquaOptima Pump Station Optimizer Lite.

## Purpose

The ranking service compares observed pump/combo performance evidence from the Sprint 7 shadow model against the existing MVP baseline/fallback control reference.

It is intended for operator review and future Operations Console evidence display, not for control.

## Inputs

- Accepted `LearnerSample` records collected only from clean replay/runtime cycles.
- Current baseline recommendation for the cycle.
- Minimum sample threshold per combo.

## Output

`AdvisoryRankingResult` contains:

- `readiness`: `ready` or `insufficient_data`.
- `baseline_combo_key`: the running combo implied by the baseline recommendation.
- `candidates`: ranked combo evidence ordered by lower estimated specific energy.
- `top_candidate`: best advisory candidate when data is ready.
- `baseline_rank`: baseline combo rank when it has enough data.
- `delta_vs_baseline_specific_energy_kwh_per_m3`: top candidate minus baseline specific energy when both are ranked.
- `reason_codes`: stable audit reasons such as `no_ready_candidates`, `advisory_ranking_ready`, `top_candidate_matches_baseline`, or `top_candidate_differs_from_baseline`.
- `influences_control`: always `False`.

## Safety boundary

This contract is advisory-only.

- No learner/AI/Console direct write path.
- No uncontrolled or newly introduced PLC/PAC/SCADA write path.
- Existing MVP baseline control remains the authority/fallback.
- Ranking output is evidence, not a command.
- Ranking output must not mutate `ControlIntent`.
- Ranking output must always serialize `influences_control=false`.

## Demo flag

```bash
python scripts/run_optimizer_lite_demo.py \
  --config config/examples/legacy_station_001.yaml \
  --replay tests/fixtures/replay/legacy_station_replay.jsonl \
  --cycles 4 \
  --learner-shadow \
  --learner-performance-shadow \
  --advisory-ranking-shadow
```

Expected current replay shape:

```text
advisory_ranking readiness=insufficient_data top_combo=None baseline_combo=pump_1 baseline_rank=None influences_control=False
```

This is correct for the current fixture because only one replay cycle is clean enough for learning. The ranking refuses to promote a top advisory candidate until enough per-combo evidence exists.
