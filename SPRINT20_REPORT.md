# Sprint 20 Report — EPANET `[OPTIONS] Viscosity` Parsing (parser-only)

## Goal

Add fallback EPANET `[OPTIONS] Viscosity` parsing as a parser-only
compatibility feature, and document / verify that the current
Hazen-Williams dPHM core is viscosity-independent.

Sprint 18 added a non-density demand-scaling axis (`Demand Multiplier`);
Sprint 19 added a density-scaling axis (`Specific Gravity`); both
propagated their resolved value to the places where it actually
mattered. Sprint 20 follows the same parse-and-validate cadence for
`Viscosity`, but **does not** propagate the resolved value to any
hydraulic field. Under Hazen-Williams head loss

```
h_L = 10.67 · L · Q^1.852 / (C^1.852 · D^4.87)
```

there is no viscosity term — the empirical roughness coefficient `C`
absorbs the fluid's frictional behaviour and the flow exponent is
fixed at `1.852` regardless of Reynolds number. Sprint 20 is therefore
a parser sprint: parse the directive, validate it, fail loudly on
invalid input, document the rationale, and assert through tests that
adding the directive changes nothing in the loaded `Network`.

## Files changed

| File                                                              | Change                                                                    |
|-------------------------------------------------------------------|---------------------------------------------------------------------------|
| `src/aquaoptima/dphm/inp_io.py`                                   | Sprint 20 module-docstring note, `_VISCOSITY_KEY` + `_DEFAULT_VISCOSITY` constants, `resolve_viscosity` helper, parse-only call from `_fallback_parse`, `resolve_viscosity` added to `__all__`. |
| `tests/dphm/test_inp_viscosity.py`                                | New — 68 Sprint 20 tests (resolver, parser case/whitespace, invalid-value rejection, hydraulic invariance across SI / US fixtures, HEAD / POWER pump invariance, PRV / TCV invariance, orthogonality with Demand Multiplier and Specific Gravity, existing-fixture preservation, optional WNTR parity). |
| `docs/epanet-inp-import.md`                                       | New "Viscosity (Sprint 20)" section, header + options-table update, Roadmap entries for Darcy-Weisbach and WNTR-side viscosity. |
| `SPRINT20_REPORT.md`                                              | New — this file.                                                          |

No new fixtures were shipped. Sprint 20 viscosity behaviour is fully
exercised through tmp-path INP fixtures, keeping `docs/examples/` at
ten files (the same count as after Sprint 18).

## Viscosity parser — design

- `resolve_viscosity(opts: dict[str, str]) -> float` is the public
  helper (mirrors the Sprint 18 / 19 `resolve_demand_multiplier` /
  `resolve_specific_gravity` shape).
- Default `1.0` when the directive is absent or empty (pure water at
  ~20 °C).
- Accepts any strictly-positive finite value.
- Raises `ValueError` with a clear message on zero, negative,
  non-finite (NaN or Inf), or non-numeric input.
- The directive's option key is a single token (`Viscosity`); the
  standard `_parse_options` single-token branch already handles
  case-insensitive parsing and whitespace collapsing, so no
  multi-word special-casing was needed.

Constants:

- `_VISCOSITY_KEY = "VISCOSITY"` — canonical map key.
- `_DEFAULT_VISCOSITY = 1.0`.

The exported public surface gains `resolve_viscosity` in
`aquaoptima.dphm.inp_io.__all__`. (Like the Sprint 18 / 19 resolvers,
it is not re-exported from the top-level `aquaoptima.dphm` package —
direct import from `inp_io` follows the prior precedent.)

## Why Hazen-Williams is viscosity-independent

EPANET's `Viscosity` directive only changes calculations that depend
on a Reynolds number — i.e. the Darcy-Weisbach head-loss formula
through the Colebrook-White / Swamee-Jain friction factor. The
current dPHM core (`aquaoptima.dphm.hazen_williams`, `residuals.py`,
the analytic Jacobian, and `newton_solve`) implements only the
Hazen-Williams branch, whose head-loss expression contains no
kinematic-viscosity factor: the fluid's frictional behaviour is
absorbed into the empirical roughness coefficient `C`, and the flow
exponent is fixed at `1.852` regardless of Reynolds.

Concretely, viscosity cannot enter any of the following fields under
Hazen-Williams without changing the mathematical model:

- Junction baseline demands.
- Reservoir / tank fixed-head boundaries.
- Pipe length, diameter, c_factor.
- HEAD pump curve coefficients (head-vs-flow, already in metres).
- POWER pump surrogate coefficients (depend on power, nominal-flow
  anchor, shut-off multiplier, and specific gravity — not viscosity).
- PRV downstream fixed-head boundary value (pressure-to-head
  conversion depends on the pressure-unit table and Specific Gravity
  for true pressure units — not viscosity).
- TCV effective Hazen-Williams length (depends on K, K_minor,
  diameter, Q_nom, c_factor — not viscosity).
- Newton-solve heads and flows on a stable fixture.

The Sprint 20 test suite asserts each of these explicitly, so a
future regression that tries to fold viscosity into any of them will
fail loudly.

## Fallback parser behaviour

- Parses `Viscosity` as a single-token key, case- and
  whitespace-tolerant.
- Resolves the value via `resolve_viscosity(opts)`, which validates
  defaults, finite-positive requirement, and the four invalid-value
  error surfaces.
- **Discards** the resolved value; no downstream code consumes it.
- Fails loudly on invalid viscosity values (zero, negative, NaN,
  Inf, non-numeric) so EPANET-produced fixtures still get a clear
  error message at parse time, preserving the fail-fast contract.

## WNTR behaviour

WNTR's treatment of `[OPTIONS] Viscosity` is ambiguous across
releases — some versions parse it into
`wn.options.hydraulic.viscosity`, others may ignore it, and WNTR's
internal simulator only consults the value when the Darcy-Weisbach
formula is selected. To avoid double-conversion or hidden
discrepancies, Sprint 20 **leaves the WNTR adapter structurally
unchanged**:

- The fallback parser is authoritative for Sprint 20 viscosity
  parsing and validation.
- All Sprint 11–19 WNTR parity (HEAD / POWER / PRV / TCV / demand
  multiplier) remains green; the targeted suite reports
  `835 passed, 1 skipped` with `wntr==1.4.0` installed.
- The new optional WNTR parity test
  (`test_wntr_fallback_parity_with_viscosity_directive`) only asserts
  that adding a `Viscosity` directive to an LPS loop does not break
  either back-end and that demand sums still agree; it does not
  assert agreement on any viscosity-derived quantity (under
  Hazen-Williams, no such quantity exists).
- The pre-existing
  `tests/dphm/test_wntr_optional_import.py::test_wntr_unavailable_message`
  guard remains the single SKIPPED case (intentionally skips when
  WNTR is installed). All other WNTR-gated tests pass.

`docs/epanet-inp-import.md` documents the WNTR ambiguity explicitly
under "Viscosity (Sprint 20) → WNTR adapter behaviour" and adds two
Roadmap entries (Darcy-Weisbach branch; explicit WNTR-side viscosity
handling).

## Test / solve / invariance evidence

68 new tests in `tests/dphm/test_inp_viscosity.py`, organised into
the following groups:

- `resolve_viscosity` defaults and validation (10 tests):
  defaults from missing/empty, six parametrised valid positive
  values, zero, negative, NaN/Inf (both signs), non-numeric.
- Two-word option key tolerance is a no-op for the one-word
  `Viscosity` key, but case / whitespace tolerance is still pinned
  across 6 directive-row variants.
- Parser rejects invalid `Viscosity` values with clear messages
  (7 parametrised cases: zero, zero-as-`0.0`, negative, NaN, Inf,
  -Inf, non-numeric).
- LPS loop hydraulic invariance under viscosity:
  - demands invariant across 4 viscosity values,
  - fixed-head values + mask invariant across 4 viscosity values,
  - pipe geometry (length, diameter, c_factor) invariant across
    4 viscosity values,
  - Newton-solve heads and flows identical between viscosity-present
    and viscosity-absent runs on the same fixture.
- GPM loop hydraulic invariance (US-customary): converted SI
  demands, fixed-head values, and pipe geometry invariant across
  3 viscosity values.
- HEAD pump coefficients invariant across 3 viscosity values.
- POWER pump coefficients invariant across 3 viscosity values.
- PRV PSI conversion invariant across 3 viscosity values (with and
  without `Specific Gravity 2.0` present).
- TCV effective resistance (length / diameter / c_factor) invariant
  across 3 viscosity values.
- Orthogonality: Demand Multiplier scaling preserved under
  viscosity; Specific Gravity PRV PSI scaling preserved under
  viscosity; three-way option-map collision check
  (`Demand Multiplier`, `Specific Gravity`, `Viscosity` all parse
  independently).
- Existing fixtures preserved byte-for-byte:
  Sprint 11 SI loop, Sprint 16 GPM loop, Sprint 18 GPM-with-DM,
  Sprint 17 GPM+PSI PRV, Sprint 14 POWER pump, Sprint 12 HEAD pump.
- Optional WNTR parity: SI loop demand parity unchanged under no
  directive; LPS loop demand parity unchanged when a `Viscosity 1.2`
  directive is added.

The Newton-solve invariance test
(`test_lps_loop_newton_solve_invariant_under_viscosity`) is the
strongest single piece of evidence: solving the LPS loop fixture
twice — once with no viscosity directive, once with
`Viscosity 2.0` — yields heads agreeing to `1e-9` absolute and
flows agreeing to `1e-12` absolute under `newton_solve` with the
analytic Jacobian.

## Tests added / updated

Added:

- `tests/dphm/test_inp_viscosity.py` (68 tests).

Updated:

- None. Sprint 20 is parser-only and does not perturb any existing
  helper's call surface, so no other test file required changes.

## Validation commands and results

```bash
$ python -m pip install -e .
Successfully installed aquaoptima-dphm-pinn-0.1.0

$ python -m pytest tests/dphm tests/models tests/training tests/dataio -q
835 passed, 1 skipped, 3 warnings in 93.87s (0:01:33)

$ python -m pytest tests -q
843 passed, 1 skipped, 3 warnings in 97.40s (0:01:37)

$ python -m compileall src tests
(clean — no SyntaxErrors reported)

$ git status --short
 M docs/epanet-inp-import.md
 M src/aquaoptima/dphm/inp_io.py
?? SPRINT20_REPORT.md
?? tests/dphm/test_inp_viscosity.py
```

Test-count delta vs Sprint 19:

- Targeted: 767 → 835 (+68 viscosity tests).
- Full: 775 → 843 (+68 viscosity tests).

The single SKIPPED case is the pre-existing
`tests/dphm/test_wntr_optional_import.py::test_wntr_unavailable_message`
guard, which intentionally skips when WNTR is installed.

## Compatibility notes

- `resolve_viscosity` follows the same defensive shape as Sprint 18 /
  19 resolvers: the resolver itself is consumed directly by tests,
  and the fallback parser invokes it once per load for validation
  only.
- The fallback parser's single-token option key handling is reused
  unchanged — no edits to `_parse_options` were required.
- WNTR back-end behaviour is preserved on every Sprint 11–19
  fixture; the optional viscosity parity test only adds an extra
  assertion that adding a `Viscosity` directive to an LPS loop does
  not break the WNTR back-end.
- The Sprint 11 / 16 / 17 / 18 / 19 shipped fixtures are unchanged
  and load with identical demands, fixed-head values, pump
  coefficients, and valve surrogates (none of them carries a
  `Viscosity` directive).
- The exported public surface gains `resolve_viscosity` in
  `aquaoptima.dphm.inp_io.__all__`.

## Known limitations

- **No WNTR-side viscosity translation.** Documented in
  `docs/epanet-inp-import.md` and listed in the roadmap. WNTR-loaded
  networks with `[OPTIONS] Viscosity` may store the value in
  different attributes across releases; Sprint 20 does not attempt
  to mirror that behaviour because the dPHM core is
  viscosity-independent.
- **No Darcy-Weisbach branch.** Sprint 20 explicitly defers
  introducing a Darcy-Weisbach / Reynolds / friction-factor model.
  That is the only place viscosity would carry physical meaning.
- **No `Viscosity` shipped fixture.** Sprint 20 covers the parser
  surface with tmp-path fixtures only, mirroring the Sprint 19
  decision to keep `docs/examples/` small.
- **No new hydraulics.** All demands, fixed heads, pipe / pump /
  valve dimensions, HEAD pump curves, POWER pump surrogates,
  PRV / TCV translations, and Newton-solve outputs are unchanged.
- **Active valve / control physics remains out of scope.** PRV
  pressure-boundary surrogate semantics are unchanged.
- **No interaction with `[ENERGY]`, `[PATTERNS]`, or any
  time-varying state.** All of those remain out of scope per
  Sprint 20's hard scope boundaries.

## Verdict

**APPROVED.**

All Sprint 20 hard gates met:

- Targeted pytest: 835 passed, 1 skipped (pre-existing WNTR-install
  skip).
- Full pytest: 843 passed, 1 skipped.
- compileall: clean.
- `SPRINT20_REPORT.md` written.
- `resolve_viscosity` exercised by 10 dedicated resolver tests plus
  integration through the parser.
- Invalid viscosity values raise clearly through both the resolver
  and the fallback parser.
- Hydraulic invariance under Hazen-Williams proven across LPS and
  GPM loop fixtures (demands, fixed heads, geometry, Newton-solve
  heads / flows).
- HEAD pump coefficients unaffected by viscosity (3 parametrised
  cases).
- POWER pump coefficients unaffected by viscosity (3 parametrised
  cases).
- PRV / TCV surrogate parameters unaffected by viscosity, including
  the PRV PSI + Specific Gravity combined path.
- Demand multiplier tests still pass and remain independent of
  viscosity.
- Specific gravity tests still pass and remain independent of
  viscosity.
- Existing SI / GPM / pressure / demand / SG fixture behaviour
  preserved.
- HEAD pump tests still pass; POWER pump tests still pass;
  PRV / TCV valve tests still pass.
- WNTR optional tests skip/pass cleanly.
- No secret files / strings introduced.
- `git status` contains only Sprint 20 changes.

Additional WNTR-installed gates met (`wntr==1.4.0`):

- Sprint 13 HEAD parity unchanged.
- Sprint 14 POWER parity unchanged.
- Sprint 15 PRV / TCV parity unchanged.
- Sprint 18 demand-multiplier WNTR parity unchanged.
- Sprint 19 SG-related WNTR parity (loose-tolerance PSI guard)
  unchanged.
- WNTR ambiguity around `Viscosity` is documented in
  `docs/epanet-inp-import.md` and called out in the Known
  limitations section above.

## Sprint 21 recommendation

**Recommended Sprint 21 focus: fallback EPANET `[REPORT]` /
`[TIMES]` parsing as a no-op surface**, keeping the same parse-and-
validate cadence but layered on the steady-state core.

Concretely:

- Add explicit silent-skip recognition for any time-aware section
  whose presence the parser currently tolerates by accident
  (`[TIMES]`, `[REPORT]`, `[CONTROLS]`, `[RULES]`,
  `[EMITTERS]`, `[QUALITY]`, `[SOURCES]`, `[REACTIONS]`,
  `[MIXING]`). All of these are already in `_IGNORED_SECTIONS` but
  none has dedicated tests proving the parser ignores their
  internal grammar variations without false positives.
- Add per-section tests that exercise representative content from
  the EPANET 2.2 user manual to confirm the fallback parser still
  loads the network cleanly, and that any malformed content inside
  a tolerated section does not silently leak into a `[PIPES]` /
  `[OPTIONS]` row.
- Defer to a future sprint: introducing a Darcy-Weisbach branch
  (the place viscosity would actually be propagated),
  `[PATTERNS]`-aware time-varying demand, `[ENERGY]` parsing,
  WNTR-side `Specific Gravity` and `Viscosity` translation, and
  any real PLC / PAC / SCADA adapter work.

This keeps Sprint 21 a parser-only sprint (matching the Sprint 17–20
cadence) and avoids leaping into hydraulics changes before the
entire `[OPTIONS]` surface and the silently-ignored sections are
auditable end-to-end. After Sprint 21 the natural next jump is
either Darcy-Weisbach (the first hydraulics change to honour
`Viscosity`) or `[PATTERNS]` (the first time-aware feature to honour
`Demand Multiplier`'s pattern column).
