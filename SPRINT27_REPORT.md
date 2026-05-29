# AOPSO Sprint 27 — Data profile, safety guardrails, leakage guard & unit validation (A+B pivot)

## Context

AOPSO pivoted to an OFFLINE, ADVISORY-ONLY product after Sprint 26 FAILed the
LOCKED March 2026 holdout (0/8 vs persistence). Sprint 27 adds the foundation
layer the A+B advisory artifacts need to be trusted: a unit/schema validator,
explicit governance-aware scorecard wiring, and a re-runnable profile +
isolation report. No model is trained; no contract is written; no edge or
write-capable connector is added.

The HARD SAFETY BOUNDARY is unchanged and is now mechanically enforced in the
scorecard itself: `evaluation_mode=offline_only`, `write_path=none`,
`influences_control=false`, `site_integration_allowed=false`. A governance
violation FAILs the scorecard regardless of metrics.

## Files added

- `src/aquaoptima/advisory/schema_validation.py` — pure validators and
  scorecard helpers (no IO unless a path is passed; no edge import; no
  write-connector):
  - `AxisTaxonomyResult` (frozen dataclass; `ok`, `errors`, `to_dict()`),
  - `validate_axis_taxonomy(...)` — asserts the active set is exactly the
    eight expected axes, the masked axis is excluded, every axis has a unit
    in `AXIS_UNITS`, and every active axis maps to a real backing column in
    `CANONICAL_AXIS_TO_COLUMN` (masked axis → `None`),
  - `NormalizationCoverageResult` (frozen dataclass; `ok`, `errors`,
    `to_dict()`),
  - `validate_normalization_coverage(stats_path | mapping)` — exact-coverage
    check (no missing, no extra), finite mu/sigma, sigma > 0,
  - `build_governance_block(split_manifest, modeling_roots,
    normalization_stats)` — composes holdout isolation, modeling-source
    import/connector scan, axis taxonomy, and normalization coverage into one
    audit block with `governance_status: "PASS"|"FAIL"`,
  - `apply_governance_to_verdict(acceptance_gate, governance_block)` — on
    governance FAIL, forces `verdict="FAIL"`, `passed=False`, and appends a
    `governance_guardrails` criterion; on governance PASS the gate is
    returned unchanged,
  - `DEFAULT_MODELING_ROOTS` — the single source of truth for the four
    modeling source dirs scanned by the scorecard
    (`src/aquaoptima/advisory`, `…/training`, `…/models`, `…/dataio`).
- `scripts/sprint27_profile_report.py` — CLI that runs the Yilan profiler
  (subset-capable via `--nrows` / `YILAN_PROFILER_NROWS`, with a 50,000-row
  safety cap unless `YILAN_PROFILER_FULL=1` is set) and the governance block
  against the real split + the real normalization stats, then writes
  `data/profiling/sprint27_isolation_report.json`. **Exits non-zero on
  governance FAIL** (so CI can gate on it). Supports `--skip-profile` for
  governance-only fast runs.
- `tests/advisory/test_schema_validation.py` — 11 new tests covering
  taxonomy + normalization coverage success/failure paths (injected via
  parameters so the real modules are never mutated).
- `tests/advisory/test_scorecard_governance.py` — 9 new tests covering
  `build_governance_block` PASS/FAIL paths and `apply_governance_to_verdict`
  pass-through + verdict-override semantics, plus an end-to-end test
  proving a leaky split + a synthetically passing acceptance gate
  → scorecard verdict FAIL.

## Files changed

- `src/aquaoptima/training/evaluation.py`
  - imports `build_governance_block`, `apply_governance_to_verdict`,
    `DEFAULT_MODELING_ROOTS` from `aquaoptima.advisory.schema_validation`,
  - `evaluate(...)`: after the per-horizon block is scored, builds the
    governance block from the loaded manifest + the norm-stats path,
    applies `apply_governance_to_verdict` to `acceptance_gate`, and embeds
    `governance` inside `safety`. Metrics-based verdicts are unchanged when
    governance passes; a governance failure forces FAIL with an explicit
    `governance_guardrails` criterion,
  - `evaluate_multi_horizon(...)`: builds the same governance block,
    applies `apply_governance_to_verdict` to the assembled `packaging_gate`,
    and embeds `governance` inside `safety` (mirroring the single-horizon
    behaviour at the top-level verdict).

## Wiring behaviour

The scorecard now carries a `safety.governance` block with four named
sub-guards:

```json
{
  "safety": {
    "...": "...",
    "governance": {
      "governance_status": "PASS|FAIL",
      "holdout_isolation":      { "isolated": bool, "leaked_keys": [...], ... },
      "import_connector_scan":  { "clean": bool, "violations": [...], ... },
      "axis_taxonomy":          { "ok": bool, "errors": [...], ... },
      "normalization_coverage": { "ok": bool, "errors": [...], ... }
    }
  }
}
```

`governance_status` is `"PASS"` iff every sub-guard is ok. When it is
`"FAIL"`, the scorecard's `acceptance_gate` (single-horizon) or
`packaging_gate` (multi-horizon) is forced to FAIL via
`apply_governance_to_verdict`:

- `verdict` → `"FAIL"`,
- `passed` → `false`,
- `governance_override` → `true`,
- a `governance_guardrails` criterion is appended with the list of failing
  sub-guards and their concrete details (`leaked_keys`, `violations`,
  taxonomy/coverage `errors`).

A governance PASS leaves the metrics-based verdict untouched, so previously
green tests keep their PASS verdicts and only gain the new audit block.

## Test counts

| Suite                                   | Sprint 26 | Sprint 27 | Δ      |
| --------------------------------------- | --------- | --------- | ------ |
| `tests/advisory -q`                     | 21        | **41**    | +20    |
| `tests -q` (full)                       | 2441      | **2461**  | +20    |

Single skip: `tests/dphm/test_wntr_optional_import.py:371` ("WNTR is
installed; ImportError path not exercised here") — unchanged from Sprint 26.

## Verification commands / results

```
$ python -m pytest tests/advisory -q
.........................................                                [100%]
41 passed in 0.18s

$ python -m pytest tests -q
2461 passed, 1 skipped, 3 warnings in 124.11s (0:02:04)

$ python scripts/sprint27_profile_report.py --skip-profile \
    --output data/profiling/sprint27_isolation_report.json
governance_status: PASS
report -> data/profiling/sprint27_isolation_report.json
```

Real-data governance block (against the production
`data/splits/yilan_2025_split_v1.json` + cached
`data/normalization/yilan_2025_train_stats.json`):

- `holdout_isolation`: isolated=true, 213 train/val keys checked,
  zero March-2026 leakage,
- `import_connector_scan`: clean=true, 35 files scanned across the four
  modeling roots, zero forbidden edge imports / write-connector tokens,
- `axis_taxonomy`: ok=true, the eight expected active axes
  (`edge_flow`, `edge_power`, `edge_pump_speed`, `edge_status`,
  `node_demand`, `node_level`, `node_pressure`, `node_status`), masked
  `edge_valve_position` excluded,
- `normalization_coverage`: ok=true, exact-cover of the eight axes, every
  axis has finite mu and sigma > 0.

## Data-reality notes

- **Mode coverage "other" bucket.** The Sprint 23 profiler surfaced an
  ~31.6% `other` bucket — rows that are neither `auto` nor `manual`
  truthy. The split builder only consumes the `auto` rows, so the `other`
  bucket does NOT bias the train/val/holdout-isolation guard, but it IS
  load-bearing for any future product analysis (it represents real
  idle / unlabelled operating periods at the Yilan site). The
  `sprint27_profile_report.py` CLI emits the per-mode breakdown into
  the isolation report whenever the profiler runs (anything from a
  50K-row subset up to the full year-long scan, gated by
  `YILAN_PROFILER_FULL=1`).
- **Masked axis is real.** `edge_valve_position` has no backing column at
  the Yilan site (no telemetered valve position). The validators encode
  this directly: the masked axis must be excluded from the active set AND
  must map to `None` in `CANONICAL_AXIS_TO_COLUMN`. Any future change that
  silently activates the masked axis fails the taxonomy guard.
- **`edge_status` near-constant.** The pump is on 99.85% of the time
  (sigma ≈ 0.011 in the cached stats), but sigma > 0, so the
  normalization-coverage guard still passes. This is intentional: the
  Sprint 26 reframe handles `edge_status` as a continuous near-constant
  axis; the guard does NOT reject it on physical grounds, only on
  numerical degeneracy.

## Safety boundary (re-asserted, mechanically enforced)

- No imports from `aquaoptima.edge` / `aquaoptima_contracts.edge` in any of
  the four modeling roots (verified by the in-scorecard scan, 35 files,
  every run).
- `aquaoptima_contracts` is read-only — no edits.
- `evaluation_mode=offline_only`, `write_path` is `scorecard_json_only`
  (evaluator) / `report_json_only` (Sprint 27 CLI) / `none` (split
  manifest), `influences_control=false`, `site_integration_allowed=false`.
- The full 489K-row CSV is never read in unit tests; the profiler is
  subset-capable via `YILAN_PROFILER_NROWS` and the CLI defaults to a
  50,000-row safety cap unless `YILAN_PROFILER_FULL=1` is set.

SPRINT27_STATUS: COMPLETE
