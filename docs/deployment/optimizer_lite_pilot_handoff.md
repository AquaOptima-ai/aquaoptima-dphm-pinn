# Optimizer Lite pilot handoff checklist

This handoff covers the integrated Optimizer Lite quick-win bundle from Sprints 7–10.

## Bundle scope

- Shadow learned pump/combo performance evidence.
- Advisory ranking and baseline comparison evidence.
- Read-only Operations Console evidence API.
- Deployment readiness JSON gate/report.

## Required pre-pilot commands

```bash
python -m compileall -q aquaoptima_lite tests scripts
python -m pytest tests/unit tests/contract tests/replay -q
python scripts/check_optimizer_lite_readiness.py \
  --config config/examples/legacy_station_001.yaml \
  --replay tests/fixtures/replay/legacy_station_replay.jsonl \
  --cycles 4
python scripts/run_optimizer_lite_demo.py \
  --config config/examples/legacy_station_001.yaml \
  --replay tests/fixtures/replay/legacy_station_replay.jsonl \
  --cycles 4 \
  --learner-shadow \
  --learner-performance-shadow \
  --advisory-ranking-shadow
```

## Expected current readiness

The current legacy station replay should report:

- `status=ready_for_pilot_review` for packaging/readiness gates.
- `audit_count=4`.
- `read_only=true`.
- `influences_control=false`.
- Console evidence endpoint present.

The learner, performance model, and advisory ranking are expected to remain conservative on the current small fixture:

- learner status: `insufficient_data`;
- performance model readiness: `insufficient_data`;
- advisory ranking readiness: `insufficient_data`.

This is not a pilot blocker. It means the bundle is safe and evidence-capable, but does not yet have enough clean site samples to promote learned advisory recommendations.

## Operator review checklist

Before any pilot run, confirm:

1. Site tag map and units are correct for the target station.
2. Existing commissioned MVP baseline authority is preserved.
3. No learner/AI/Console direct write path is enabled.
4. No uncontrolled or newly introduced PLC/PAC/SCADA write path exists.
5. Manual mode, trips, interlocks, and authority gate remain binding.
6. Console evidence is reviewed as advisory/evidence only, not commands.
7. Readiness report is archived with the pilot package.
8. Customer/site data policy permits the replay/config evidence being used.

## Safety boundary

Optimizer Lite packaging/readiness work is evidence-only:

- No live OT binding is introduced by this bundle.
- No command emission is introduced by learner, advisory, Console, or readiness paths.
- No setpoint output is introduced by learner, advisory, Console, or readiness paths.
- Existing MVP baseline control remains the authority/fallback where commissioned.

## Merge audit note

After merge, verify `origin/main` contains:

- Sprint 7 commit: `ec4f160 feat: add shadow pump performance model`.
- Sprint 8 commit: `83cdd9f feat: add advisory ranking shadow evidence`.
- Sprint 9 commit: `b422a03 feat: add console evidence API`.
- Sprint 10 commit: `c7ec812 feat: add optimizer lite deployment readiness gate`.

Then run the pre-pilot commands above from `main` and archive the readiness JSON output.
