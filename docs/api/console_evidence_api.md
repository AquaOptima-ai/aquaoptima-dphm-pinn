# Operations Console evidence API

Sprint 9 adds a read-only evidence endpoint for future Operations Console consumption:

```text
GET /console/evidence/current
```

The endpoint aggregates the latest Optimizer Lite runtime state and latest audit evidence into one JSON-serializable operator report.

## Payload shape

Top-level fields:

- `service`: always `optimizer_lite`.
- `has_cycle`: whether the runtime has processed at least one cycle.
- `site_id`, `runtime_mode`, `config_hash`: latest runtime identity fields.
- `read_only`: always `true`.
- `influences_control`: always `false`.
- `safety`: read-only safety assertions.
- `quality`: latest quality decision.
- `baseline`: latest baseline/fallback recommendation.
- `learner_shadow`: latest learner shadow evidence from the audit store.
- `performance_model`: nested performance model evidence when present.
- `advisory_ranking`: nested advisory ranking evidence when present.

## Safety boundary

This endpoint is for evidence display only.

- No learner/AI/Console direct write path.
- No uncontrolled or newly introduced PLC/PAC/SCADA write path.
- Existing MVP baseline control remains the authority/fallback.
- Console-facing payloads are evidence, not commands.
- The endpoint does not mutate `ControlIntent`.
- The endpoint returns `read_only=true` and `influences_control=false`.

## Empty state

Before the first runtime cycle, the endpoint still returns a stable payload:

```json
{
  "service": "optimizer_lite",
  "has_cycle": false,
  "read_only": true,
  "influences_control": false,
  "baseline": null,
  "learner_shadow": {},
  "performance_model": {},
  "advisory_ranking": {}
}
```

This lets Operations Console clients render a safe disconnected/awaiting-data state without inferring commands or write authority.
