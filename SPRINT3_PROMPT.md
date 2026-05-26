# Sprint 3 — MVP baseline wrapper, audit store, and APIs

Continue from completed Sprint 2 in this worktree. Do not remove or rewrite Sprint 2 contracts unless tests require a small compatible fix.

## Correct PLC/PAC framing
- Existing MVP baseline PLC/PAC control path must be preserved as a product capability.
- This sprint still must not implement live PLC writes or network clients.
- Represent baseline output as `source=baseline_mvp` and pass it through authority gate.

## Goal
Wrap existing MVP `PumpController` behavior behind a canonical baseline interface and expose current status/recommendation evidence through APIs.

## Create/modify
```
aquaoptima_lite/baseline/__init__.py
aquaoptima_lite/baseline/interface.py
aquaoptima_lite/baseline/mvp_compat.py
aquaoptima_lite/baseline/mvp_wrapper.py
aquaoptima_lite/baseline/fallback.py
aquaoptima_lite/storage/__init__.py
aquaoptima_lite/storage/schema.sql
aquaoptima_lite/storage/sqlite_store.py
aquaoptima_lite/api/__init__.py
aquaoptima_lite/api/app.py
aquaoptima_lite/api/routes_status.py
aquaoptima_lite/api/routes_snapshot.py
aquaoptima_lite/api/routes_quality.py
aquaoptima_lite/api/routes_recommendation.py
aquaoptima_lite/app/__init__.py
aquaoptima_lite/app/cycle.py
aquaoptima_lite/app/main.py
tests/contract/test_api_contracts.py
tests/unit/test_mvp_compat.py
tests/unit/test_audit_store.py
tests/unit/test_runtime_cycle.py
```

## Requirements
- `mvp_compat.py` maps `StationSnapshot` to current MVP input shape: `system_mode`, `sensor_data.measured_head`, `sensor_data.measured_flow`, per-pump lower-case keys like `pumpa_on`, `pumpa_freq`, `pumpa_flow`, `pumpa_efficiency`, and `demand_info.target_head/flow_min/flow_max`.
- Add target demand fields to config or demo defaults if Sprint 2 did not include them.
- `mvp_wrapper.py` should work with a fake baseline engine in tests. If importing the real legacy PumpController is brittle, implement a wrapper that supports dependency injection and a clear import error fallback.
- Define canonical recommendation dataclass if not already present: source, mode, pump setpoints, reason codes, confidence, write_intent/future flag, authority decision.
- `app/cycle.py` runs one cycle: snapshot -> quality -> baseline recommendation -> authority gate -> audit store -> current state.
- SQLite audit store writes one row per cycle with JSON columns for snapshot, quality, recommendation, authority, runtime mode, config hash, created_at.
- FastAPI if available, otherwise Flask if available. Keep API app small. Endpoints: `/status`, `/snapshot/current`, `/quality/current`, `/recommendation/current`.
- API should be testable via FastAPI TestClient or Flask test client.

## Verification before finish
Run:
```
python -m compileall -q aquaoptima_lite tests
python -m pytest tests/unit tests/contract -q
python - <<'PY'
from aquaoptima_lite.api.app import create_app
app = create_app()
print('APP_OK', bool(app))
PY
git diff --check
```
Leave files unstaged. Do not commit. Report summary and tests.
