# dPHM-PINN Product Roadmap

## Operating model

- GitHub is the source of truth for product, architecture, safety, validation, deployment, and code documentation.
- Plane is the source of truth for sprint execution, status, phase progress, module ownership, prompts, QA summaries, and commit/PR links.

## Phase 1 — Foundation + EPANET diagnostics

Purpose: build the dPHM/PINN foundation and make topology/import limitations visible.

Representative sprints: 1-33.

Deliverables:

- dPHM primitives, residuals, solver, analytic Newton path.
- dPHM-PINN training and GNN support.
- EPANET topology, pump, valve, unit, and option import.
- WNTR parity checks where feasible.
- Diagnostics for ignored/deferred sections.
- Import-quality report.

## Phase 2 — Shadow-mode MVP

Purpose: enable offline/read-only shadow-mode evaluation.

Representative sprints: 34-39.

Deliverables:

- Telemetry tag-map adapter.
- Shadow replay dataset builder.
- dPL calibration prototype.
- Advisory safety contract.
- Shadow-mode runtime harness.
- Export/deployment package.

## Phase 3 — Advisory / supervised control product

Purpose: move from read-only shadow evidence to operator-facing advisory and limited supervised-write workflows.

Representative sprints: 40-51.

Deliverables:

- Shadow results evaluator.
- Advisory recommendation engine.
- Operator feedback loop.
- Safety case v1.
- Mocked write-path simulator.
- Limited supervised-write contract.
- Site integration readiness package.

## Phase 4 — Qualified PAC-like edge product

Purpose: evolve the edge runtime into a validated PAC-compatible product candidate.

Representative sprints: 52-70.

Deliverables:

- Deterministic edge runtime.
- Watchdog/heartbeat/fail-safe state machine.
- Local override/operator authority.
- Industrial protocol hardening.
- Cybersecurity baseline.
- Signed deployment bundle.
- Hardware-in-the-loop and fault-injection tests.
- Commissioning/SAT package.
- Controlled live pilot.
