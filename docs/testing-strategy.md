# Testing Strategy

AquaOptima dPHM-PINN is developed test-first. Every Sprint 1–4.5
production module landed via a strict TDD loop: write a failing test,
observe the failure, implement the minimum code to flip it green, and
run the full suite to confirm no regression.

## Suite layout

```
tests/
├── dphm/
│   ├── test_hazen_williams.py
│   ├── test_pump_affinity.py
│   ├── test_incidence.py
│   ├── test_residuals.py
│   ├── test_feasibility.py
│   ├── test_fixtures.py
│   ├── test_network.py
│   ├── test_solver.py
│   ├── test_diagnostics.py
│   └── test_autograd.py
├── topology/
│   └── test_graph_builder.py
├── dataio/
│   ├── test_window_dataset.py
│   ├── test_telemetry_aliases.py   # Sprint 4.5
│   ├── test_tag_map.py             # Sprint 4.5
│   └── test_quality.py             # Sprint 4.5
├── models/
│   ├── test_dphm_pinn.py
│   ├── test_losses.py
│   └── test_lambda_scheduler.py
└── training/
    ├── test_training_smoke.py
    └── test_ablations.py
```

## Categories

- **Unit tests** — every public function/class in `dphm`, `dataio`,
  `models`, and `training` has at least one direct test of inputs,
  outputs, and the boundary that raises `ValueError`.
- **Physics consistency tests** — `test_residuals`, `test_solver`, and
  `test_autograd` exercise the differentiable physics on the three
  hand-built fixtures (branch / single-loop / pump). These are the
  trust anchor for everything that comes after.
- **Shape / dtype contract tests** — every dataclass and every
  loss/forward path asserts the shape it returns. Real bugs we have
  shipped before came from silent broadcasting on a wrong axis; the
  tests pin shapes explicitly.
- **No-future-leakage test** — `WindowDataset` has a dedicated test
  that proves `target_*` is strictly outside `x_seq`'s window.
- **Smoke / training tests** — `test_training_smoke` and
  `test_ablations` run a few iterations of the real training loop on
  synthetic data and assert finiteness and parameter movement; they
  catch regressions without taking long enough to hurt CI.

## Conventions

- **Determinism.** Every randomised test seeds its own
  `torch.Generator`. No global seed mutation.
- **No hidden defaults.** Tests pass every parameter the function
  takes; we never rely on a default to make a test pass.
- **One concept per test.** A failing test points at one specific
  invariant. Multi-assertion tests are reserved for "shape of a
  return value" type checks where the assertions are coupled.
- **Failure-mode tests.** Every dataclass that validates at
  construction has at least one test per failure branch. The point is
  to make the *error message* a reviewed part of the API.

## Commands

```bash
python -m pytest tests/dataio -q              # subset
python -m pytest tests -q                     # whole suite
python -m compileall src tests                # bytecode sanity check
```

Sprint 4.5 ends with **183 tests passing** (Sprint 4's 154 + 29 new
dataio tests). Any merge that does not run `python -m pytest tests -q`
clean should be reverted.
