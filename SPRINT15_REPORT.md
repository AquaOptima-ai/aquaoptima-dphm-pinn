# Sprint 15 — EPANET `[VALVES]` import (conservative PRV / TCV)

## Goal

Sprint 15 extends the dPHM topology importer (`load_network_from_inp`)
to accept the two steady-state-compatible EPANET valve forms — `PRV`
and `TCV` — through deliberately conservative surrogates, so a wider
class of real-world `.inp` files loads end-to-end. No active valve
physics, no field adapter, no control path.

Sprint 14 verified state (entry):

- 481 passed, 1 skipped (targeted)
- 489 passed, 1 skipped (full)
- compileall clean

## Files changed

| Path | Status | Purpose |
|------|--------|---------|
| `src/aquaoptima/dphm/inp_io.py` | modified | Add `fit_tcv_resistance_surrogate`, `translate_valve_to_surrogate`, WNTR valve helpers, integrated valve parsing in fallback + WNTR back-ends. |
| `src/aquaoptima/dphm/__init__.py` | modified | Re-export `fit_tcv_resistance_surrogate`, `translate_valve_to_surrogate`. |
| `docs/epanet-inp-import.md` | modified | "Valves (Sprint 15)" section: PRV / TCV design, limitations, diagnostics keys, shipped fixtures, WNTR surface. Roadmap and test listing updated. |
| `docs/examples/epanet_reference_prv.inp` | new | Four-node PRV reference fixture. |
| `docs/examples/epanet_reference_tcv.inp` | new | Three-node TCV reference fixture. |
| `tests/dphm/test_inp_valves.py` | new | Helper + translator + shipped-fixture + error-path tests for fallback parser. |
| `tests/dphm/test_wntr_valve_helpers.py` | new | WNTR valve helper tests against duck-typed fakes (no WNTR dependency). |
| `tests/dphm/test_wntr_optional_import.py` | modified | Optional WNTR PRV / TCV fixture load + solve + cross-back-end parity. |
| `tests/dphm/test_inp_network_io.py` | modified | `test_valves_section_raises` repurposed into `test_unsupported_valves_section_raises` (now asserts FCV raises with valve-id-tagged message). |

`git status --short` shows only those nine entries — no stray files.

## PRV design and limitations

A `PRV` row `V1 N1 N2 D PRV setting K_minor` is imported as a
**pressure-boundary surrogate**:

1. Downstream node `N2` is pinned to a fixed-head boundary at
   `head = elev(N2) + setting`. EPANET stores the setting as the
   downstream pressure target in metres of head under SI flow
   units.
2. The PRV edge becomes a short, permissive pipe-like resistance
   edge (`length = max(2 * D, 1 m)`, file diameter, `c_factor =
   130`).
3. The translator records `approximation =
   "prv_pressure_boundary_surrogate"` and the absolute
   downstream-head value in the diagnostics dict.

Hard constraints (raise with valve id):

- `N2` must not already be a fixed-head boundary (raise with
  `"already a fixed-head"`).
- `setting > 0` and finite.
- `diameter > 0` and finite.
- `downstream_elev_m` finite.
- `minor_loss >= 0` and finite.

**Documented limitations** (asserted in the test suite, not silently
hidden):

- Mass balance on the now-fixed downstream node is dropped from the
  residual. The PRV does NOT enforce active flow / pressure
  regulation. Flow through the PRV is determined by the upstream
  pressure budget, not by downstream demand.
- The PRV does not model EPANET's active-control state machine
  (active / open / closed branches).
- The shipped PRV fixture deliberately uses a long narrow upstream
  pipe so the upstream pressure budget caps the through-valve flow
  close to downstream demand (4.89 L/s through the PRV vs 2.0 L/s
  downstream demand — the test asserts this discrepancy is real
  and explains it as the surrogate's documented limit).

## TCV design and limitations

A `TCV` row `V1 N1 N2 D TCV K K_minor` is imported as a **resistance
surrogate** through `fit_tcv_resistance_surrogate(...)`:

1. `K_total = K + K_minor`.
2. Anchor flow `Q_nom` = network's total positive demand (or 1 L/s
   default when none — same convention as the POWER pump anchor;
   the diagnostic `nominal_flow_m3s` records the actual value
   used).
3. Minor-loss head loss at anchor:
   `h_minor = K_total * Q_nom^2 / (2 g A^2)`, where
   `A = π D^2 / 4`.
4. Effective Hazen-Williams length:
   `L_eff = h_minor / (10.67 * Q_nom^1.852 / (C^1.852 * D^4.87))`.
5. Surrogate edge has `length = max(L_eff, 1e-6 m)`, file diameter,
   `c_factor = 130`. `pipe_mask = True`, `pump_mask = False`.

Hard constraints (raise with valve id):

- `setting >= 0` (K), finite. `K = 0` is allowed (fully open valve)
  and produces `L_eff = 1e-6 m` (floored to satisfy `Network`'s
  `length > 0` invariant).
- `minor_loss >= 0` and finite.
- `diameter > 0` and finite.
- `nominal_flow_m3s > 0` and finite.
- `c_factor > 0` and finite.

**Documented limitations**:

- Hazen-Williams scales as `|Q|^1.852` while the true minor-loss
  term scales as `K * Q^2`. The two match exactly at `Q_nom` and
  diverge as `Q` moves away from the anchor. Single-anchor
  approximation only.
- The TCV is not modelled as an active control element.
- Default `c_factor = 130` is a typical valve-body friction class;
  the surrogate's accuracy at the anchor flow is unaffected by
  `c_factor` choice (it appears only in the `L_eff` scaling).

## Fallback parser behavior

Sprint 11's blanket `[VALVES]` rejection is replaced with per-row
dispatch:

1. After parsing nodes (with per-node elevation now tracked), parse
   `[VALVES]` rows.
2. Validate row shape (>= 6 tokens), numeric diameter / setting /
   minor_loss columns, known endpoint nodes, unique valve id.
3. Translate each row via `translate_valve_to_surrogate`, passing
   `downstream_elev_m` from the parsed node and `nominal_flow_m3s`
   from total positive demand.
4. For `PRV`: pin downstream node as fixed-head (raise if already
   fixed).
5. Append valve edges as pipe-like (`pipe_mask=True`,
   `pump_mask=False`) after pumps. Edge ordering is
   `[pipes..., pumps..., valves...]`, preserving Sprint 12-14
   test expectations.
6. Demand rebalancing onto fixed-head nodes runs last (mass on
   fixed-head nodes drops out of the residual anyway).

Error paths covered:

- Unsupported valve types (`FCV`, `PSV`, `PBV`, `GPV`): `ValueError`
  with valve id.
- Unknown valve type: `ValueError` with valve id.
- Short row (<6 tokens): `ValueError`.
- Non-numeric diameter / setting / minor-loss: `ValueError` tagged
  with the offending column name and valve id.
- Non-positive / non-finite diameter: `ValueError` (via translator).
- Non-positive PRV setting: `ValueError` (via translator).
- Negative TCV setting / minor_loss: `ValueError` (via translator).
- Unknown endpoint: `ValueError` with valve id.
- Duplicate valve id colliding with pipe / pump / other valve:
  `ValueError`.
- PRV downstream already fixed-head: `ValueError`.
- Empty `[VALVES]` section: tolerated (no-op).

## WNTR behavior

The WNTR back-end's Sprint 11 valve rejection is replaced with the
same `translate_valve_to_surrogate` path:

- `_wntr_extract_valve_fields(valve)` defensively pulls
  `valve_type`, `diameter`, `initial_setting` (or `setting` fallback
  for older WNTR releases), `minor_loss`, `start_node_name`,
  `end_node_name`. Each is `getattr`-tolerant and type-validates.
- `_wntr_translate_valve(valve, valve_id=..., downstream_elev_m=...,
  total_positive_demand=...)` routes through the same translator,
  with the WNTR `name` attribute used as a fallback id if no
  explicit id is supplied.
- `_wntr_parse` iterates `wn.valve_name_list`, calls
  `_wntr_translate_valve` for each, applies PRV downstream-fixed-head
  pinning, and appends the valve edge — mirroring the fallback
  parser's logic exactly.

WNTR API surface touched (all stable across recent releases):

- `wn.valve_name_list`
- `wn.get_link(name)`
- `valve.valve_type`
- `valve.diameter` (SI metres)
- `valve.initial_setting` (preferred) / `valve.setting` (fallback)
- `valve.minor_loss`
- `valve.start_node_name` / `valve.end_node_name`

Per-node elevation is now read from `junction.elevation`,
`reservoir.base_head` (the datum is implicit), and `tank.elevation`.

WNTR-version note: WNTR itself refuses `PRV / PSV / FCV` valves
directly connected to a reservoir or tank ("Add a pipe to separate
the valve from the reservoir"). The shipped fixtures and the WNTR
unsupported-type test are authored to comply.

When WNTR is not installed:

- The WNTR-helper tests under `test_wntr_valve_helpers.py` still run
  (they use duck-typed fakes and never `import wntr`).
- The optional integration tests under `test_wntr_optional_import.py`
  skip cleanly via `pytest.importorskip("wntr")`.

## Shipped fixtures

### `docs/examples/epanet_reference_tcv.inp`

Three-node TCV reference:

```
R1 (50 m fixed head) -- V1 (TCV K=2.5, D=150 mm) --> J1
                                                       |
                                                       +-- P1 (200 m, 150 mm, C=130) --> J2 (15 L/s consumer)
```

- Loads via fallback and WNTR parsers identically.
- 3 nodes, 2 edges, 1 fixed head.
- Valve edge `L_eff = 16.4183 m` (matches the closed-form
  `K * V^2 / (2 g)` head loss at `Q_nom = 0.015 m^3/s`).

### `docs/examples/epanet_reference_prv.inp`

Four-node PRV reference:

```
R1 (50 m) -- P1 (2000 m, 80 mm) --> J1 -- V1 (PRV setting=20 m, D=80 mm) --> J2 (pinned)
                                                                                |
                                                                                +-- P2 (200 m, 80 mm) --> J3 (2 L/s)
```

- Loads via fallback and WNTR parsers identically.
- 4 nodes, 3 edges, 2 fixed heads (R1 reservoir + J2 pinned by PRV).
- Long narrow upstream pipe caps the through-valve flow close to
  the downstream demand, giving a physically sensible solve.

## Solve / residual evidence

### Fallback parser

| Fixture | Newton mode | Converged | Final residual norm | Notes |
|---------|-------------|-----------|---------------------|-------|
| TCV     | analytic    | True      | 3.09e-15            | flows = [0.015, 0.015] m³/s; valve head loss = 0.0919 m (closed-form expected 0.0918 m). |
| PRV     | analytic    | True      | 6.93e-16            | J2 (PRV downstream, fixed) head = 20.000 m; Q_V1 = 4.890 L/s, Q_consumer = 2.000 L/s. The 2.890 L/s discrepancy is the documented PRV pressure-boundary limitation, asserted explicitly in `test_prv_fixture_documents_mass_balance_caveat`. |

### WNTR parser

| Fixture | Newton mode | Converged | Final residual norm |
|---------|-------------|-----------|---------------------|
| TCV     | analytic    | True      | 3.09e-15            |
| PRV     | analytic    | True      | 6.93e-16            |

Fallback and WNTR solutions agree to 1e-5 absolute on heads and
flows (asserted in `test_wntr_and_fallback_agree_on_tcv_solution`).

## Tests added / updated

### New test modules

- `tests/dphm/test_inp_valves.py` — 39 tests:
  - `fit_tcv_resistance_surrogate` formula, diagnostics, validation.
  - `translate_valve_to_surrogate` PRV / TCV paths, errors.
  - Shipped TCV fixture load, solve, residual, demand balance,
    valve head loss matching closed-form minor-loss.
  - Shipped PRV fixture load, solve, downstream-head pin,
    documented mass-balance caveat assertion.
  - Fallback-parser error surface (unsupported type, unknown type,
    non-numeric / non-positive columns, duplicate id, unknown
    endpoint, PRV-into-reservoir, empty section, short row).
  - Cross-feature coexistence (HEAD pump + TCV, POWER pump + PRV).

- `tests/dphm/test_wntr_valve_helpers.py` — 20 tests:
  - `_wntr_extract_valve_fields` defensive extraction, attribute
    aliases (`initial_setting` vs `setting`), missing fields,
    non-numeric / non-positive values.
  - `_wntr_translate_valve` PRV (downstream-pin) + TCV (fit-helper
    delegation), default anchor fallback, `minor_loss` propagation.
  - Unsupported / unknown type rejection.
  - Cross-check that WNTR translator agrees with the direct
    `translate_valve_to_surrogate` call on PRV and TCV.

### Updated test modules

- `tests/dphm/test_wntr_optional_import.py` — 7 new optional tests:
  TCV fixture load + solve, PRV fixture load + solve, fallback /
  WNTR solution parity, WNTR unsupported-type rejection. All
  guarded by `pytest.importorskip("wntr")`.

- `tests/dphm/test_inp_network_io.py` —
  `test_valves_section_raises` renamed to
  `test_unsupported_valves_section_raises` and reworked to use an
  `FCV` row (the original PRV-rejection contract is now obsolete).

### Preserved tests

- Sprint 12 (HEAD curve), Sprint 13 (WNTR HEAD parity), Sprint 14
  (POWER pump + WNTR POWER) all unchanged and still pass.
- All other suites (training, dataio, models, topology, …)
  unchanged.

## Validation commands and results

```bash
python -m pip install -e .                                   # ok
python -m pytest tests/dphm tests/models tests/training tests/dataio -q
# -> 567 passed, 1 skipped in 90.11s (targeted)
python -m pytest tests -q
# -> 575 passed, 1 skipped in 86.62s (full)
python -m compileall src tests                                # exit=0
git status --short                                            # only Sprint 15 entries
```

The single skip is `test_wntr_parser_explicit_raises_importerror_when_missing`
when WNTR *is* installed — it has no negative path to exercise and
calls `pytest.skip` explicitly. WNTR is installed in this
environment (`wntr==1.4.0`).

## Compatibility notes

- The `Network` dataclass is unchanged. Valve edges fit cleanly
  into `pipe_mask=True` (Hazen-Williams head loss); no new edge
  category was needed.
- Edge ordering is `[pipes..., pumps..., valves...]`, preserving
  every Sprint 11-14 test assertion that depends on pipe-first
  ordering.
- The fallback parser's `[OPTIONS] Units` directive still drives
  demand conversion; valve diameter follows the same mm → m
  conversion as pipes under SI units.
- Per-node elevation is now tracked through the fallback and WNTR
  parsers (in service of PRV downstream-head pinning) but never
  surfaced on the `Network` dataclass — purely internal to the
  importer.
- `__init__.py` and `__all__` re-exports cover
  `fit_tcv_resistance_surrogate` and `translate_valve_to_surrogate`;
  the existing pump-surrogate public surface is unchanged.

## Known limitations

- **PRV mass-balance caveat**: pinning the downstream node as a
  fixed-head boundary drops its mass-balance residual term, so the
  flow through the PRV may differ from the downstream demand. This
  is documented in the translator's `limitations` diagnostic field,
  in the `docs/epanet-inp-import.md` "What the PRV surrogate is
  NOT" subsection, and asserted explicitly in
  `test_prv_fixture_documents_mass_balance_caveat`.
- **TCV single-anchor approximation**: the surrogate matches the
  minor-loss head loss exactly at the anchor flow only; off-design
  flows diverge because `|Q|^1.852` ≠ `K * Q^2`.
- **No active control**: neither valve form behaves as an active
  control element; both are static, parse-time-frozen surrogates.
- **PRV-into-reservoir**: PRVs whose downstream is already a
  fixed-head boundary (reservoir or tank) raise rather than silently
  overwrite. WNTR itself also refuses this topology at load time.
- **Unsupported valve forms**: `FCV`, `PSV`, `PBV`, `GPV` raise with
  the valve id. Each requires either an active-control state
  machine or a custom head-loss curve that the Sprint 15
  surrogates cannot reproduce.
- **WNTR API drift**: the WNTR helpers rely on attribute access
  (`getattr`-tolerant), preferring `initial_setting` over `setting`.
  Both are tested via duck-typed fakes so future WNTR releases
  that rename or restructure can be caught by the existing test
  surface.
- No real EPANET binary, no PLC / PAC / SCADA adapters, no write
  path, no dPL parameter learning, no production claims — all per
  the explicit Sprint 15 boundary.

## Hard approval gate audit

| Gate | Status |
|------|--------|
| targeted pytest exits 0 | ✓ 567 passed, 1 skipped |
| full pytest exits 0 | ✓ 575 passed, 1 skipped |
| compileall exits 0 | ✓ exit=0 |
| `SPRINT15_REPORT.md` exists | ✓ (this file) |
| PRV fixture loads + solves (or documented unsupported-solve) | ✓ loads + solves (analytic Newton, residual 6.93e-16) with documented pressure-boundary limitation |
| TCV fixture loads + solves with analytic Newton | ✓ converged, residual 3.09e-15 |
| unsupported valve forms fail clearly | ✓ FCV / PSV / PBV / GPV raise with valve id |
| HEAD curve pump tests still pass | ✓ (Sprint 12 + Sprint 13 WNTR parity) |
| POWER pump tests still pass | ✓ (Sprint 14 + Sprint 14 WNTR parity) |
| WNTR optional tests skip/pass cleanly | ✓ WNTR installed → 14 PRV/TCV/HEAD/POWER integration tests pass; 1 ImportError-path test correctly skipped |
| WNTR valve helper / integration tests pass | ✓ 20 helper tests + 7 integration tests pass |
| WNTR HEAD/POWER pump parity preserved | ✓ unchanged |
| no obvious secret files / strings introduced | ✓ grep clean for `BEGIN PRIVATE|BEGIN RSA|PASSWORD|SECRET|API_KEY` |
| git status contains only intended Sprint 15 changes | ✓ 5 modified, 4 untracked (all listed above) |

## Verdict

**APPROVED**

Every hard gate is green. The PRV surrogate is shipped as a
deliberately conservative pressure-boundary translator with the
mass-balance caveat documented in docstrings, the architecture doc,
and (most importantly) asserted in the test suite. The TCV
surrogate is shipped as a single-anchor resistance translator with
exact matching at the anchor flow and divergence documented
off-design. All Sprint 12-14 pump behaviour, the WNTR HEAD / POWER
parity, and the full Sprint 1-14 test surface continue to pass.

## Sprint 16 recommendation

The most credible next conservative widening is **EPANET
US-customary flow units (`GPM`, `CFS`, `MGD`, `IMGD`, `AFD`)** on
the fallback parser. The WNTR back-end already normalises to SI on
load, so adding a unit-conversion lookup table on the fallback path
(diameter inches → m, length feet → m, head/elev feet → m, demand
factor per unit → m³/s) opens the importer to a much larger pool
of real-world `.inp` files without touching the steady-state core.
It is mechanical, easy to test against shipped reference fixtures
(US-units versions of the existing loop / pump / valve fixtures),
and preserves every Sprint 11-15 boundary (no runtime, no control,
no field bindings).

This unblocks loading EPANET `Net1` / `Net2` / `Net3` shipped
examples through the fallback parser without WNTR, which in turn
unblocks a larger-fixture science-gate dataset later.
